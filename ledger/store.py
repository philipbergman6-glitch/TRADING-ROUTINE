"""Writes the order lifecycle to Postgres.

The ledger records, it does not decide. Every function here takes an already-
made decision and persists it; none of them consult the risk engine or the
broker. Keeping the record separate from the decider is what lets you answer
"why did this order exist, and who allowed it" months later.

Refused orders are recorded as deliberately as accepted ones -- an audit trail
containing only successes answers none of the interesting questions.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from risk_engine import OrderProposal, ValidationResult

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
ENGINE_VERSION = "risk_engine/0.1.0"

__all__ = ["Ledger", "LedgerOrder", "connect", "migrate"]


def connect(dsn: str | None = None) -> psycopg.Connection:
    """Open a connection. Hard-fails rather than defaulting to a local guess."""
    resolved = dsn or os.environ.get("DATABASE_URL")
    if not resolved:
        raise RuntimeError(
            "DATABASE_URL is not set; refusing to guess at a ledger database"
        )
    return psycopg.connect(resolved, row_factory=dict_row)


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply every migration in order. Idempotent by construction."""
    applied: list[str] = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        with conn.cursor() as cur:
            cur.execute(path.read_text())
        applied.append(path.stem)
    conn.commit()
    return applied


@dataclass(frozen=True)
class LedgerOrder:
    id: uuid.UUID
    idempotency_key: str
    status: str


class Ledger:
    """A thin, deep interface over the ledger tables.

    Deliberately narrow: callers get four verbs, not a query builder. The
    schema is free to change behind them.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    # -- writes -------------------------------------------------------------

    def record_decision(
        self,
        proposal: OrderProposal,
        result: ValidationResult,
        *,
        idempotency_key: str,
        strategy_version: str,
        research_ref: str | None = None,
    ) -> LedgerOrder:
        """Persist a proposed order together with the engine's verdict.

        Written in a single transaction: an order without its validation, or a
        validation without its violations, is not a state this ledger can hold.
        """
        order_id = uuid.uuid4()
        status = "proposed" if result.approved else "refused"
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders (id, idempotency_key, symbol, side, qty, price,
                                    stop_price, trail_percent, strategy_version,
                                    research_ref, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    idempotency_key,
                    proposal.symbol,
                    proposal.side.value,
                    proposal.qty,
                    proposal.price,
                    proposal.stop_price,
                    proposal.trail_percent,
                    strategy_version,
                    research_ref,
                    status,
                ),
            )
            validation_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO validations (id, order_id, approved, engine_version)
                VALUES (%s, %s, %s, %s)
                """,
                (validation_id, order_id, result.approved, ENGINE_VERSION),
            )
            for violation in result.violations:
                cur.execute(
                    """
                    INSERT INTO validation_violations (validation_id, rule, detail)
                    VALUES (%s, %s, %s)
                    """,
                    (validation_id, violation.rule.value, violation.detail),
                )
            self._append_audit(
                cur,
                order_id,
                "order.validated",
                {"approved": result.approved, "reasons": result.reasons()},
            )
        return LedgerOrder(order_id, idempotency_key, status)

    def record_submission(
        self,
        order_id: uuid.UUID,
        *,
        broker_order_id: str,
        response: dict,
        http_status: int | None = None,
    ) -> None:
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                   SET status = 'submitted',
                       broker_order_id = %s,
                       submitted_at = now()
                 WHERE id = %s AND status = 'proposed'
                """,
                (broker_order_id, order_id),
            )
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"order {order_id} is not in 'proposed' state; refusing to "
                    "record a submission against it"
                )
            self._record_response(cur, order_id, "submit", response, http_status)
            self._append_audit(
                cur, order_id, "order.submitted", {"broker_order_id": broker_order_id}
            )

    def record_fill(
        self, order_id: uuid.UUID, *, filled_qty: Decimal, filled_price: Decimal
    ) -> None:
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders SET status = 'filled', filled_at = now()
                 WHERE id = %s AND status = 'submitted'
                """,
                (order_id,),
            )
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"order {order_id} is not in 'submitted' state; refusing to "
                    "record a fill against it"
                )
            self._append_audit(
                cur,
                order_id,
                "order.filled",
                {"qty": str(filled_qty), "price": str(filled_price)},
            )

    def record_stop(
        self, order_id: uuid.UUID, *, response: dict, http_status: int
    ) -> None:
        """Record the protective stop's broker response, accepted or refused.

        Separate from the buy on purpose: the whole point of tracking it is to
        make an unprotected position *visible*. The response is kept verbatim
        either way, but only an accepted one is audited as `stop.placed` -- a
        refusal that recorded `stop.placed` made the immutable record assert
        something untrue (#37).
        """
        if http_status is None:
            raise ValueError(
                "http_status is required when recording a protective stop: a "
                "caller that cannot say what the broker answered cannot say "
                "whether the position is protected"
            )
        placed = http_status < 400
        with self._conn.transaction(), self._conn.cursor() as cur:
            self._record_response(cur, order_id, "stop", response, http_status)
            self._append_audit(
                cur,
                order_id,
                "stop.placed" if placed else "stop.rejected",
                {} if placed else {"http_status": http_status},
            )

    # -- reads --------------------------------------------------------------

    def order_by_idempotency_key(self, key: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE idempotency_key = %s", (key,))
            return cur.fetchone()

    def audit_trail(self, order_id: uuid.UUID) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_type, payload, occurred_at
                  FROM audit_events
                 WHERE order_id = %s
                 ORDER BY occurred_at, id
                """,
                (order_id,),
            )
            return cur.fetchall()

    def unprotected_orders(self) -> list[dict]:
        """Filled buys with no *accepted* protective stop.

        This is the query a reconciliation loop would run. The loop itself is
        not built (see ARCHITECTURE.md), but the ledger is shaped so that the
        question is answerable rather than requiring a schema change later.

        Protection requires a stop response the broker *accepted*. Keying off
        the mere existence of a stop row counted a refusal as protection and
        hid the position this query exists to surface (#37). `http_status` is
        NULL only on rows written before it was mandatory; NULL < 400 is not
        true, so those legacy rows read as unprotected -- the safe direction.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.id, o.symbol, o.qty, o.filled_at
                  FROM orders o
                 WHERE o.side = 'buy'
                   AND o.status = 'filled'
                   AND NOT EXISTS (
                       SELECT 1 FROM broker_responses r
                        WHERE r.order_id = o.id
                          AND r.kind = 'stop'
                          AND r.http_status < 400
                   )
                 ORDER BY o.filled_at
                """
            )
            return cur.fetchall()

    def violation_counts(self) -> list[dict]:
        """Which rules refuse most often -- a GROUP BY, not a text search."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT rule, count(*) AS n
                  FROM validation_violations
                 GROUP BY rule
                 ORDER BY n DESC, rule
                """
            )
            return cur.fetchall()

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _record_response(cur, order_id, kind, response, http_status) -> None:
        cur.execute(
            """
            INSERT INTO broker_responses (id, order_id, kind, http_status, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (uuid.uuid4(), order_id, kind, http_status, json.dumps(response)),
        )

    @staticmethod
    def _append_audit(cur, order_id, event_type, payload) -> None:
        cur.execute(
            """
            INSERT INTO audit_events (id, order_id, event_type, payload)
            VALUES (%s, %s, %s, %s)
            """,
            (uuid.uuid4(), order_id, event_type, json.dumps(payload)),
        )

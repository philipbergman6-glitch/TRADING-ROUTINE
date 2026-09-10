"""Live-path ledger writes — the seam between validation/execution and Postgres.

The Ledger class records; these helpers decide *when* and *that* the live path
must record. Callers get a narrow surface: persist a decision, persist a broker
outcome. They do not get a query builder or a soft-skip when the database is
down — mandatory means fail closed.

Does not bind validate→submit (#19 / #26). Emitting a ledger order id so the
caller can attach a later broker response is recording, not a validated-order
token.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from risk_engine import OrderProposal, ValidationResult

from .store import Ledger, LedgerOrder, connect, migrate

__all__ = [
    "EXIT_LEDGER",
    "DEFAULT_STRATEGY_VERSION",
    "open_live_ledger",
    "persist_decision",
    "persist_broker_response",
]

# validate_order / record_broker_response exit when the ledger cannot be written.
EXIT_LEDGER = 6

DEFAULT_STRATEGY_VERSION = "TRADING-STRATEGY"


def open_live_ledger(*, dsn: str | None = None, run_migrate: bool = True) -> Ledger:
    """Open the ledger for a live write. Hard-fails if DATABASE_URL is unset."""
    resolved = dsn if dsn is not None else os.environ.get("DATABASE_URL")
    if not resolved:
        raise RuntimeError(
            "DATABASE_URL is not set; refusing to run the live path without a ledger"
        )
    conn = connect(resolved)
    if run_migrate:
        migrate(conn)
    return Ledger(conn)


def persist_decision(
    ledger: Ledger,
    proposal: OrderProposal,
    result: ValidationResult,
    *,
    idempotency_key: str | None = None,
    strategy_version: str = DEFAULT_STRATEGY_VERSION,
    research_ref: str | None = None,
) -> LedgerOrder:
    """Mandatory record of the engine verdict — approved and refused alike."""
    key = idempotency_key or f"live-{uuid.uuid4()}"
    return ledger.record_decision(
        proposal,
        result,
        idempotency_key=key,
        strategy_version=strategy_version,
        research_ref=research_ref,
    )


def persist_broker_response(
    ledger: Ledger,
    order_id: uuid.UUID,
    *,
    kind: str,
    response: dict[str, Any],
    http_status: int,
    broker_order_id: str | None = None,
) -> None:
    """Persist a broker outcome against an already-recorded decision.

    Only kinds the Ledger API already supports: ``submit`` and ``stop``.
    Cancel/poll writers are deliberately not invented here (#28 / schema gaps).
    """
    if kind == "submit":
        if not broker_order_id:
            raise ValueError(
                "broker_order_id is required for kind=submit: the ledger refuses "
                "a submission without a broker id"
            )
        ledger.record_submission(
            order_id,
            broker_order_id=broker_order_id,
            response=response,
            http_status=http_status,
        )
        return
    if kind == "stop":
        ledger.record_stop(order_id, response=response, http_status=http_status)
        return
    raise ValueError(
        f"unsupported broker response kind {kind!r}; live path supports "
        "'submit' and 'stop' only (Ledger API; no invented cancel writer)"
    )

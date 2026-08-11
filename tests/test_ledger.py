"""Ledger integration tests — against a real Postgres, never a mock.

Skipped cleanly when DATABASE_URL is unset, so a Docker problem costs you these
tests and never the risk-engine safety tests.

    docker compose up -d
    DATABASE_URL=postgresql://trading:trading@localhost:5433/trading pytest
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

from risk_engine import (
    OrderProposal,
    PortfolioState,
    Side,
    validate_order,
)

psycopg = pytest.importorskip("psycopg", reason="psycopg not installed")

DSN = os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="DATABASE_URL unset; skipping ledger tests"),
]

from ledger import Ledger, connect, migrate  # noqa: E402


@pytest.fixture(scope="module")
def conn():
    connection = connect(DSN)
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def clean(conn):
    """audit_events is append-only, so TRUNCATE (not DELETE) resets it."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE orders, audit_events RESTART IDENTITY CASCADE")
    conn.commit()
    yield


@pytest.fixture
def ledger(conn):
    return Ledger(conn)


def portfolio(**overrides) -> PortfolioState:
    defaults = dict(
        equity=Decimal("100000"),
        cash=Decimal("100000"),
        is_paper=True,
        positions=(),
        trades_this_week=0,
    )
    return PortfolioState(**{**defaults, **overrides})


def buy(**overrides) -> OrderProposal:
    defaults = dict(
        symbol="AAPL",
        qty=Decimal("100"),
        side=Side.BUY,
        price=Decimal("100"),
        trail_percent=Decimal("10"),
    )
    return OrderProposal(**{**defaults, **overrides})


def key() -> str:
    return f"test-{uuid.uuid4()}"


# --- migrations --------------------------------------------------------------


def test_migrations_are_idempotent(conn):
    assert migrate(conn) == ["001_init"]
    assert migrate(conn) == ["001_init"]


# --- recording decisions -----------------------------------------------------


def test_approved_order_is_recorded_as_proposed(ledger):
    proposal = buy()
    result = validate_order(proposal, portfolio())
    assert result.approved

    order = ledger.record_decision(
        proposal, result, idempotency_key=key(), strategy_version="v1"
    )
    assert order.status == "proposed"

    trail = ledger.audit_trail(order.id)
    assert [e["event_type"] for e in trail] == ["order.validated"]
    assert trail[0]["payload"]["approved"] is True


def test_refused_order_is_recorded_too(ledger):
    """An audit trail with only successes answers none of the interesting
    questions."""
    proposal = buy(trail_percent=None)  # unprotected
    result = validate_order(proposal, portfolio())
    assert not result.approved

    order = ledger.record_decision(
        proposal, result, idempotency_key=key(), strategy_version="v1"
    )
    assert order.status == "refused"

    counts = {row["rule"]: row["n"] for row in ledger.violation_counts()}
    assert counts["stop_required"] == 1


def test_every_violated_rule_becomes_its_own_row(ledger):
    proposal = buy(qty=Decimal("500"), trail_percent=None)
    result = validate_order(proposal, portfolio(trades_this_week=5, cash=Decimal("1000")))
    ledger.record_decision(proposal, result, idempotency_key=key(), strategy_version="v1")

    counts = {row["rule"]: row["n"] for row in ledger.violation_counts()}
    assert set(counts) >= {
        "max_position_pct",
        "max_trades_per_week",
        "sufficient_cash",
        "stop_required",
    }


# --- idempotency -------------------------------------------------------------


def test_duplicate_idempotency_key_is_refused_by_the_database(ledger):
    """Duplicate-order prevention is a constraint, not a code path that might
    be skipped."""
    proposal = buy()
    result = validate_order(proposal, portfolio())
    shared = key()
    ledger.record_decision(proposal, result, idempotency_key=shared, strategy_version="v1")

    with pytest.raises(psycopg.errors.UniqueViolation):
        ledger.record_decision(
            proposal, result, idempotency_key=shared, strategy_version="v1"
        )


def test_order_is_findable_by_idempotency_key(ledger):
    proposal = buy()
    result = validate_order(proposal, portfolio())
    shared = key()
    ledger.record_decision(proposal, result, idempotency_key=shared, strategy_version="v1")

    found = ledger.order_by_idempotency_key(shared)
    assert found["symbol"] == "AAPL"
    assert found["status"] == "proposed"
    assert ledger.order_by_idempotency_key("never-used") is None


# --- lifecycle ---------------------------------------------------------------


def approved_order(ledger):
    proposal = buy()
    result = validate_order(proposal, portfolio())
    return ledger.record_decision(
        proposal, result, idempotency_key=key(), strategy_version="v1"
    )


def test_full_lifecycle_builds_an_audit_trail(ledger):
    order = approved_order(ledger)
    ledger.record_submission(
        order.id, broker_order_id="brk-1", response={"id": "brk-1"}, http_status=200
    )
    ledger.record_fill(order.id, filled_qty=Decimal("100"), filled_price=Decimal("100.25"))
    ledger.record_stop(order.id, response={"id": "brk-2", "type": "trailing_stop"})

    assert [e["event_type"] for e in ledger.audit_trail(order.id)] == [
        "order.validated",
        "order.submitted",
        "order.filled",
        "stop.placed",
    ]


def test_cannot_record_a_fill_before_a_submission(ledger):
    """Illegal state transitions are refused, not silently applied."""
    order = approved_order(ledger)
    with pytest.raises(RuntimeError, match="not in 'submitted' state"):
        ledger.record_fill(
            order.id, filled_qty=Decimal("100"), filled_price=Decimal("100")
        )


def test_cannot_submit_the_same_order_twice(ledger):
    order = approved_order(ledger)
    ledger.record_submission(order.id, broker_order_id="brk-1", response={})
    with pytest.raises(RuntimeError, match="not in 'proposed' state"):
        ledger.record_submission(order.id, broker_order_id="brk-1", response={})


def test_refused_orders_cannot_be_submitted(ledger):
    """The ledger will not record an execution the engine never approved."""
    proposal = buy(trail_percent=None)
    result = validate_order(proposal, portfolio())
    order = ledger.record_decision(
        proposal, result, idempotency_key=key(), strategy_version="v1"
    )
    with pytest.raises(RuntimeError, match="not in 'proposed' state"):
        ledger.record_submission(order.id, broker_order_id="brk-1", response={})


# --- the question a reconciliation loop would ask ---------------------------


def test_filled_buy_without_a_stop_is_visible(ledger):
    order = approved_order(ledger)
    ledger.record_submission(order.id, broker_order_id="brk-1", response={})
    ledger.record_fill(order.id, filled_qty=Decimal("100"), filled_price=Decimal("100"))

    unprotected = ledger.unprotected_orders()
    assert [o["id"] for o in unprotected] == [order.id]

    ledger.record_stop(order.id, response={"id": "brk-2"})
    assert ledger.unprotected_orders() == []


# --- immutability ------------------------------------------------------------


def test_audit_events_cannot_be_updated(ledger, conn):
    order = approved_order(ledger)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE audit_events SET event_type = 'tampered' WHERE order_id = %s",
                (order.id,),
            )
    conn.rollback()


def test_audit_events_cannot_be_deleted(ledger, conn):
    order = approved_order(ledger)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audit_events WHERE order_id = %s", (order.id,))
    conn.rollback()


# --- schema constraints hold the line ---------------------------------------


def test_database_refuses_a_negative_quantity(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders (id, idempotency_key, symbol, side, qty, price,
                                    strategy_version, status)
                VALUES (%s, %s, 'AAPL', 'buy', -1, 100, 'v1', 'proposed')
                """,
                (uuid.uuid4(), key()),
            )
    conn.rollback()


def test_database_refuses_a_submitted_order_with_no_broker_id(conn):
    """An impossible state is impossible to store, not merely unlikely."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders (id, idempotency_key, symbol, side, qty, price,
                                    strategy_version, status)
                VALUES (%s, %s, 'AAPL', 'buy', 10, 100, 'v1', 'submitted')
                """,
                (uuid.uuid4(), key()),
            )
    conn.rollback()


def test_database_refuses_an_unknown_status(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders (id, idempotency_key, symbol, side, qty, price,
                                    strategy_version, status)
                VALUES (%s, %s, 'AAPL', 'buy', 10, 100, 'v1', 'teleported')
                """,
                (uuid.uuid4(), key()),
            )
    conn.rollback()

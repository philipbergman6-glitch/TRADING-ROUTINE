"""T4: mandatory Ledger.record_decision (+ broker response) on the live path.

Wires existing Ledger API via ledger.live_path — does NOT fold #19 (validate↔
submit token bind) or claim #28 authoritative. #40 PATCH still OPEN.
"""

from __future__ import annotations

import importlib.util
import json
import re
import os
import sys
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ledger.live_path import (
    DEFAULT_STRATEGY_VERSION,
    EXIT_LEDGER,
    open_live_ledger,
    persist_broker_response,
    persist_decision,
)
from risk_engine import (
    OrderProposal,
    PortfolioState,
    Side,
    ValidationResult,
    validate_order,
)

REPO = Path(__file__).resolve().parent.parent
VALIDATE = REPO / "scripts" / "validate_order.py"
RECORD = REPO / "scripts" / "record_broker_response.py"

LIVE_MUTATING_WORKFLOWS = (
    REPO / "routines" / "market-open.md",
    REPO / "routines" / "midday.md",
    REPO / ".claude" / "commands" / "market-open.md",
    REPO / ".claude" / "commands" / "midday.md",
    REPO / ".claude" / "commands" / "trade.md",
)

DSN = os.environ.get("DATABASE_URL")


# --- fakes ------------------------------------------------------------------


@dataclass
class FakeLedgerOrder:
    id: uuid.UUID
    idempotency_key: str
    status: str


@dataclass
class FakeLedger:
    decisions: list[dict[str, Any]] = field(default_factory=list)
    submissions: list[dict[str, Any]] = field(default_factory=list)
    stops: list[dict[str, Any]] = field(default_factory=list)

    def record_decision(
        self,
        proposal: OrderProposal,
        result: ValidationResult,
        *,
        idempotency_key: str,
        strategy_version: str,
        research_ref: str | None = None,
    ) -> FakeLedgerOrder:
        status = "proposed" if result.approved else "refused"
        order = FakeLedgerOrder(uuid.uuid4(), idempotency_key, status)
        self.decisions.append(
            {
                "proposal": proposal,
                "result": result,
                "idempotency_key": idempotency_key,
                "strategy_version": strategy_version,
                "research_ref": research_ref,
                "order": order,
            }
        )
        return order

    def record_submission(
        self,
        order_id: uuid.UUID,
        *,
        broker_order_id: str,
        response: dict,
        http_status: int | None = None,
    ) -> None:
        self.submissions.append(
            {
                "order_id": order_id,
                "broker_order_id": broker_order_id,
                "response": response,
                "http_status": http_status,
            }
        )

    def record_stop(
        self, order_id: uuid.UUID, *, response: dict, http_status: int
    ) -> None:
        self.stops.append(
            {
                "order_id": order_id,
                "response": response,
                "http_status": http_status,
            }
        )


def portfolio() -> PortfolioState:
    return PortfolioState(
        equity=Decimal("100000"),
        cash=Decimal("100000"),
        is_paper=True,
        positions=(),
        trades_this_week=0,
    )


def buy(**overrides: object) -> OrderProposal:
    defaults: dict[str, object] = dict(
        symbol="AAPL",
        qty=Decimal("10"),
        side=Side.BUY,
        price=Decimal("100"),
        trail_percent=Decimal("10"),
    )
    defaults.update(overrides)
    return OrderProposal(**defaults)  # type: ignore[arg-type]


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- live_path seam ---------------------------------------------------------


def test_persist_decision_records_approved_via_ledger_api() -> None:
    ledger = FakeLedger()
    proposal = buy()
    result = validate_order(proposal, portfolio())
    assert result.approved

    order = persist_decision(
        ledger,  # type: ignore[arg-type]
        proposal,
        result,
        idempotency_key="t4-approved",
        strategy_version="v-test",
    )
    assert order.status == "proposed"
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0]["idempotency_key"] == "t4-approved"
    assert ledger.decisions[0]["strategy_version"] == "v-test"


def test_persist_decision_records_refusal_too() -> None:
    """Refusals are the most audit-worthy events — must not skip the ledger."""
    ledger = FakeLedger()
    proposal = buy(trail_percent=None, stop_price=None)
    result = validate_order(proposal, portfolio())
    assert not result.approved

    order = persist_decision(ledger, proposal, result)  # type: ignore[arg-type]
    assert order.status == "refused"
    assert ledger.decisions[0]["result"].approved is False


def test_persist_decision_default_strategy_version() -> None:
    ledger = FakeLedger()
    proposal = buy()
    result = validate_order(proposal, portfolio())
    persist_decision(ledger, proposal, result)  # type: ignore[arg-type]
    assert ledger.decisions[0]["strategy_version"] == DEFAULT_STRATEGY_VERSION


def test_persist_broker_response_submit_calls_record_submission() -> None:
    ledger = FakeLedger()
    oid = uuid.uuid4()
    persist_broker_response(
        ledger,  # type: ignore[arg-type]
        oid,
        kind="submit",
        response={"id": "brk-1"},
        http_status=200,
        broker_order_id="brk-1",
    )
    assert ledger.submissions == [
        {
            "order_id": oid,
            "broker_order_id": "brk-1",
            "response": {"id": "brk-1"},
            "http_status": 200,
        }
    ]


def test_persist_broker_response_stop_calls_record_stop() -> None:
    ledger = FakeLedger()
    oid = uuid.uuid4()
    persist_broker_response(
        ledger,  # type: ignore[arg-type]
        oid,
        kind="stop",
        response={"id": "brk-stop"},
        http_status=200,
    )
    assert ledger.stops[0]["http_status"] == 200
    assert ledger.stops[0]["response"]["id"] == "brk-stop"


def test_persist_broker_response_rejects_invented_kinds() -> None:
    ledger = FakeLedger()
    with pytest.raises(ValueError, match="unsupported broker response kind"):
        persist_broker_response(
            ledger,  # type: ignore[arg-type]
            uuid.uuid4(),
            kind="cancel",
            response={},
            http_status=204,
        )


def test_persist_broker_response_submit_requires_broker_order_id() -> None:
    ledger = FakeLedger()
    with pytest.raises(ValueError, match="broker_order_id"):
        persist_broker_response(
            ledger,  # type: ignore[arg-type]
            uuid.uuid4(),
            kind="submit",
            response={},
            http_status=200,
        )


def test_open_live_ledger_fails_closed_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        open_live_ledger()


# --- validate_order.py CLI (mocked broker + fake ledger seam) ---------------


def test_validate_order_module_calls_persist_decision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Seam: after engine verdict, validate_order.main must persist via live_path."""
    vo = _load_script("validate_order_t4", VALIDATE)

    fake = FakeLedger()
    captured: dict[str, Any] = {}

    def fake_open(**_kwargs: object) -> FakeLedger:
        return fake

    def fake_persist(ledger, proposal, result, **kwargs):  # type: ignore[no-untyped-def]
        captured["called"] = True
        return persist_decision(ledger, proposal, result, **kwargs)

    monkeypatch.setattr(vo, "open_live_ledger", fake_open)
    monkeypatch.setattr(vo, "persist_decision", fake_persist)
    monkeypatch.setattr(vo, "read_portfolio", lambda _now, _override: portfolio())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_order.py",
            "--symbol",
            "AAPL",
            "--qty",
            "10",
            "--side",
            "buy",
            "--price",
            "100",
            "--trail-percent",
            "10",
            "--json",
            "--idempotency-key",
            "cli-seam-1",
        ],
    )
    code = vo.main()
    assert code == 0
    assert captured.get("called") is True
    assert len(fake.decisions) == 1
    assert fake.decisions[0]["idempotency_key"] == "cli-seam-1"
    out = json.loads(capsys.readouterr().out)
    assert out["approved"] is True
    assert out["ledger_order_id"] == str(fake.decisions[0]["order"].id)
    assert out["idempotency_key"] == "cli-seam-1"


def test_validate_order_refused_still_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    vo = _load_script("validate_order_t4_refused", VALIDATE)

    fake = FakeLedger()
    monkeypatch.setattr(vo, "open_live_ledger", lambda **_k: fake)
    monkeypatch.setattr(vo, "persist_decision", persist_decision)
    monkeypatch.setattr(vo, "read_portfolio", lambda _n, _o: portfolio())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_order.py",
            "--symbol",
            "AAPL",
            "--qty",
            "10",
            "--side",
            "buy",
            "--price",
            "100",
            "--json",
        ],
    )
    code = vo.main()
    assert code == vo.EXIT_REFUSED
    assert len(fake.decisions) == 1
    assert fake.decisions[0]["order"].status == "refused"


def test_validate_order_ledger_failure_exits_ledger_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vo = _load_script("validate_order_t4_fail", VALIDATE)

    def boom(**_k: object) -> FakeLedger:
        raise RuntimeError("DATABASE_URL is not set")

    monkeypatch.setattr(vo, "open_live_ledger", boom)
    monkeypatch.setattr(vo, "read_portfolio", lambda _n, _o: portfolio())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_order.py",
            "--symbol",
            "AAPL",
            "--qty",
            "10",
            "--side",
            "buy",
            "--price",
            "100",
            "--trail-percent",
            "10",
        ],
    )
    code = vo.main()
    assert code == EXIT_LEDGER


# --- record_broker_response.py CLI ------------------------------------------


def test_record_broker_response_cli_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_script("record_broker_response_t4", RECORD)

    fake = FakeLedger()
    monkeypatch.setattr(mod, "open_live_ledger", lambda **_k: fake)
    monkeypatch.setattr(mod, "persist_broker_response", persist_broker_response)

    oid = str(uuid.uuid4())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "record_broker_response.py",
            "--order-id",
            oid,
            "--kind",
            "submit",
            "--broker-order-id",
            "brk-99",
            "--http-status",
            "200",
            "--response",
            '{"id":"brk-99"}',
        ],
    )
    assert mod.main() == 0
    assert fake.submissions[0]["broker_order_id"] == "brk-99"


# --- workflow prose: live path instructs ledger writes ----------------------


_BAD_LEDGER_CAPTURE = re.compile(
    r'python3\s+-c\s+"[^"]*\["ledger_order_id"\]'
)
_HTTP_STATUS_HARDCODED = re.compile(r"--http-status\s+200\b")
_TRAIL_THEN_RECORD_KIND = re.compile(
    r"build_oto_order\.py\s+trail[\s\S]{0,500}?"
    r"record_broker_response\.py[\s\S]{0,240}?--kind\s+(?P<kind>submit|stop)",
    re.MULTILINE,
)
_OTO_THEN_RECORD_KIND = re.compile(
    r"build_oto_order\.py\s+oto[\s\S]{0,500}?"
    r"record_broker_response\.py[\s\S]{0,240}?--kind\s+(?P<kind>submit|stop)",
    re.MULTILINE,
)


@pytest.mark.parametrize("path", LIVE_MUTATING_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_instructs_ledger_record_after_order(path: Path) -> None:
    """After mutating order, routines must record broker response to the ledger."""
    text = path.read_text()
    assert "validate_order.py" in text
    assert "record_broker_response.py" in text, (
        f"{path.relative_to(REPO)}: must instruct broker-response ledger write"
    )
    assert "ledger_order_id" in text
    assert text.count("record_broker_response.py") >= 2, (
        f"{path.name}: expected multiple record_broker_response call sites"
    )


@pytest.mark.parametrize("path", LIVE_MUTATING_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_ledger_order_id_capture_quoting(path: Path) -> None:
    """Capture must use single-quoted -c so ["ledger_order_id"] is not a NameError."""
    text = path.read_text()
    assert not _BAD_LEDGER_CAPTURE.search(text), (
        f"{path.relative_to(REPO)}: double-quoted python -c with "
        '["ledger_order_id"] raises NameError under bash — use single quotes'
    )
    assert "LEDGER_ORDER_ID=$(printf \"%s\" \"$VALIDATE_JSON\" | python3 -c '" in text, (
        f"{path.relative_to(REPO)}: missing safe single-quoted LEDGER_ORDER_ID capture"
    )
    assert 'json.load(sys.stdin)["ledger_order_id"]' in text


@pytest.mark.parametrize("path", LIVE_MUTATING_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_sets_ledger_order_id_before_each_record(path: Path) -> None:
    """Every record --order-id must follow a validate --json that sets LEDGER_ORDER_ID."""
    text = path.read_text()
    lines = text.splitlines()
    record_idxs = [i for i, line in enumerate(lines) if "record_broker_response.py" in line]
    assert record_idxs, f"{path.name}: expected record_broker_response call sites"
    for i in record_idxs:
        window = "\n".join(lines[max(0, i - 30) : i + 1])
        assert re.search(r"LEDGER_ORDER_ID=", window), (
            f"{path.relative_to(REPO)}: LEDGER_ORDER_ID must be assigned near "
            f"record_broker_response (within ~30 lines above line {i + 1})"
        )
        block = "\n".join(lines[i : min(len(lines), i + 6)])
        assert '"$LEDGER_ORDER_ID"' in block, (
            f"{path.relative_to(REPO)}: record must pass --order-id \"$LEDGER_ORDER_ID\""
        )
        assert "validate_order.py" in window and "--json" in window, (
            f"{path.relative_to(REPO)}: each record must follow a validate --json "
            f"that sets LEDGER_ORDER_ID (line {i + 1})"
        )


@pytest.mark.parametrize("path", LIVE_MUTATING_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_trail_uses_kind_stop_parent_uses_submit(path: Path) -> None:
    """One trail policy matching Ledger: trail/protective → stop; parent OTO → submit."""
    text = path.read_text()
    assert "Trail/protective" in text or "trail/protective" in text.lower()
    assert "--kind stop" in text, (
        f"{path.relative_to(REPO)}: must document trail/protective --kind stop"
    )
    trail_kinds = [m.group("kind") for m in _TRAIL_THEN_RECORD_KIND.finditer(text)]
    assert trail_kinds, f"{path.name}: expected at least one trail→record pair"
    for kind in trail_kinds:
        assert kind == "stop", (
            f"{path.relative_to(REPO)}: trail place must record --kind stop "
            f"(Ledger record_stop), got --kind {kind}"
        )
    oto_kinds = [m.group("kind") for m in _OTO_THEN_RECORD_KIND.finditer(text)]
    # trade.md / market-open have OTO parent submits; midday may not.
    for kind in oto_kinds:
        assert kind == "submit", (
            f"{path.relative_to(REPO)}: parent OTO must record --kind submit, "
            f"got --kind {kind}"
        )


@pytest.mark.parametrize("path", LIVE_MUTATING_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_derives_http_status_not_hardcoded(path: Path) -> None:
    """record_broker_response must get a derived HTTP status — never hardcoded 200."""
    text = path.read_text()
    assert not _HTTP_STATUS_HARDCODED.search(text), (
        f"{path.relative_to(REPO)}: drop hardcoded --http-status 200; "
        "derive from alpaca transport (ALPACA_HTTP_STATUS_FILE / $HTTP_STATUS)"
    )
    assert "HTTP_STATUS" in text, (
        f"{path.relative_to(REPO)}: must assign HTTP_STATUS for record_broker_response"
    )
    assert '--http-status "$HTTP_STATUS"' in text, (
        f"{path.relative_to(REPO)}: record must pass --http-status \"$HTTP_STATUS\""
    )
    assert "ALPACA_HTTP_STATUS_FILE" in text, (
        f"{path.relative_to(REPO)}: must wire ALPACA_HTTP_STATUS_FILE so status "
        "is derived from curl -w, not guessed"
    )


@pytest.mark.parametrize("path", LIVE_MUTATING_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_still_keeps_t1_gate(path: Path) -> None:
    text = path.read_text()
    assert "ALPACA_RISK_OK" in text
    assert "validate_order.py" in text


def test_architecture_names_t4_live_ledger_write() -> None:
    text = (REPO / "ARCHITECTURE.md").read_text()
    assert "record_decision" in text or "persist_decision" in text
    # Honesty: #19 / authoritative still open — do not claim solved.
    assert "#19" in text or "issue #19" in text
    assert "#28" in text or "authoritative" in text.lower()


# --- integration (real Postgres) --------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not DSN, reason="DATABASE_URL unset")
def test_integration_decision_then_submission_audit_trail() -> None:
    from ledger import Ledger, connect, migrate

    conn = connect(DSN)
    migrate(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE orders, audit_events RESTART IDENTITY CASCADE")
    conn.commit()

    proposal = buy()
    result = validate_order(proposal, portfolio())
    ledger = Ledger(conn)
    order = persist_decision(
        ledger, proposal, result, idempotency_key=f"t4-int-{uuid.uuid4()}"
    )
    assert order.status == "proposed"
    persist_broker_response(
        ledger,
        order.id,
        kind="submit",
        response={"id": "brk-int-1"},
        http_status=200,
        broker_order_id="brk-int-1",
    )
    trail = ledger.audit_trail(order.id)
    assert [e["event_type"] for e in trail] == ["order.validated", "order.submitted"]
    conn.close()

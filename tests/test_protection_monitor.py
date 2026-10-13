"""Protection monitor: planning is pure and version-aware; execution drives
replace_stop and never invents a cancel/place pair."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from scripts import coordinator
from tests.store_support import fresh_stores

from risk_engine import V1, V2
from risk_engine.monitor import plan_protection
from scripts.protection_monitor import EXIT_ISSUES, execute, worst_exit
from scripts.replace_stop import EXIT_OK, EXIT_REFUSED, EXIT_RESTORED, EXIT_UNPROTECTED, Outcome
from scripts.strategy_version import PINS_FILE

NOW = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
FAR = (NOW + timedelta(days=80)).strftime("%Y-%m-%dT%H:%M:%SZ")
SOON = (NOW + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
APPROVED = json.loads(PINS_FILE.read_text())["active"]  # the live approved version



@pytest.fixture(autouse=True)
def coordinated(tmp_path, monkeypatch):
    """Recovery runs against an empty store unless a test says otherwise."""
    monkeypatch.setattr(coordinator, "open_store", fresh_stores(tmp_path))

def position(symbol, qty="100", entry="100", price="100"):
    return {"symbol": symbol, "qty": qty, "avg_entry_price": entry, "current_price": price,
            "market_value": str(Decimal(qty) * Decimal(price))}


def stop(oid, symbol, kind, level, qty="100", trail=None, expires=FAR, status="new"):
    return {"id": oid, "symbol": symbol, "side": "sell", "type": kind, "status": status, "qty": qty,
            "filled_qty": "0", "stop_price": level, "trail_percent": trail, "expires_at": expires,
            "time_in_force": "gtc"}


def test_covered_book_with_nothing_due_is_a_no_op():
    plan = plan_protection([position("AMD")], [stop("s1", "AMD", "trailing_stop", "90", trail="10")], NOW)
    assert plan.actions == [] and plan.holds == [] and plan.coverage["ok"]


def test_uncovered_position_is_an_issue_not_an_action():
    plan = plan_protection([position("AMD")], [], NOW)
    assert plan.coverage["ok"] is False and "AMD" in plan.coverage["issues"][0]
    assert worst_exit(plan, []) == EXIT_ISSUES


def test_expiring_stop_is_renewed_at_its_level_rounded_up():
    plan = plan_protection([position("XLB", price="50")],
                           [stop("s1", "XLB", "stop", "48.781", expires=SOON)], NOW)
    assert [(a.kind, str(a.stop_price)) for a in plan.actions] == [("renew", "48.79")]


def test_v1_converts_leftover_fixed_leg_when_trail_would_not_lower():
    plan = plan_protection([position("AMD", entry="100", price="101")],
                           [stop("s1", "AMD", "stop", "90")], NOW, V1)
    assert [(a.kind, str(a.trail_percent)) for a in plan.actions] == [("convert", "10")]


def test_v1_holds_fixed_leg_when_conversion_would_lower_it():
    plan = plan_protection([position("XLB", entry="52", price="50")],
                           [stop("s1", "XLB", "stop", "48.78")], NOW, V1)
    assert plan.actions == [] and "HOLD fixed 48.78" in plan.holds[0]
    assert "inside the 3% minimum" in plan.standing[0]


def test_v2_converts_only_once_gain_reaches_threshold():
    below = plan_protection([position("AMD", entry="100", price="104")],
                            [stop("s1", "AMD", "stop", "93")], NOW, V2)
    assert below.actions == [] and "below v2 conversion threshold 5%" in below.holds[0]
    above = plan_protection([position("AMD", entry="100", price="105")],
                            [stop("s1", "AMD", "stop", "93")], NOW, V2)
    assert [(a.kind, str(a.trail_percent)) for a in above.actions] == [("convert", "10")]


@pytest.mark.parametrize("params, price, expected", [
    (V1, "116", "7"), (V1, "121", "5"), (V2, "121", "7"), (V2, "114", None)])
def test_tighten_follows_the_version_ladder(params, price, expected):
    plan = plan_protection([position("MU", entry="100", price=price)],
                           [stop("s1", "MU", "trailing_stop", str(Decimal(price) * Decimal("0.9")), trail="10")],
                           NOW, params)
    got = [(a.kind, str(a.trail_percent)) for a in plan.actions]
    assert got == ([("tighten", expected)] if expected else [])


def test_tighten_never_lowers_below_resting_stop():
    # Resting trail already sits at 112 (high-water mark 124.4); mark fell to 116.
    plan = plan_protection([position("MU", entry="100", price="116")],
                           [stop("s1", "MU", "trailing_stop", "112", trail="10")], NOW, V1)
    assert plan.actions == [] and "tighten to 7% refused" in plan.holds[0]


def test_renewal_takes_precedence_over_tightening_this_run():
    plan = plan_protection([position("MU", entry="100", price="116")],
                           [stop("s1", "MU", "trailing_stop", "104.4", trail="10", expires=SOON)], NOW)
    assert [a.kind for a in plan.actions] == ["renew"]


def test_position_missing_price_fields_is_an_error():
    with pytest.raises(ValueError, match="missing"):
        plan_protection([{"symbol": "AMD", "qty": "1"}], [], NOW)


def test_execute_reruns_unprotected_then_reports_worst_exit():
    plan = plan_protection([position("AMD", price="101")], [stop("s1", "AMD", "stop", "90")], NOW)
    calls = []
    outcomes = iter([Outcome(EXIT_UNPROTECTED, "cancel_unconfirmed"), Outcome(EXIT_OK, "replaced")])

    def replace(order_id, trail_percent=None, stop_price=None):
        calls.append((order_id, trail_percent, stop_price))
        raise next(outcomes)

    results = execute(plan, replace=replace)
    assert len(calls) == 2 and calls[0] == ("s1", Decimal("10"), None)
    assert results[0]["state"] == "replaced" and worst_exit(plan, results) == 0

    def restored(*_a, **_k):
        raise Outcome(EXIT_RESTORED, "replacement_failed_old_level_restored")

    assert worst_exit(plan, execute(plan, replace=restored)) == EXIT_RESTORED

    def never(*_a, **_k):
        raise Outcome(EXIT_UNPROTECTED, "cancel_unconfirmed")

    assert worst_exit(plan, execute(plan, replace=never, reruns=2)) == EXIT_UNPROTECTED


def test_alert_delivery_failure_fails_an_otherwise_clean_run():
    import subprocess
    from scripts.protection_monitor import EXIT_ALERT_FAILED, exit_code, notify

    report = {"observed_at": "2026-10-12T14:00:00+00:00", "exit": 0, "coverage": {"issues": []},
              "results": [{"kind": "tighten", "symbol": "MPC", "state": "replaced"}], "holds": [], "standing": []}
    sent = []

    def ok(cmd, **kw):
        sent.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0)

    def refused(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 4)

    def hung(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    assert notify(report, run=ok) is True and "tighten MPC -> replaced" in sent[0]
    assert notify(report, run=refused) is False
    assert notify(report, run=hung) is False
    # A lost alert on a clean or coverage-issue run becomes exit 9; broker-state
    # outcomes (7, 8) keep their code since they are the more urgent signal.
    assert exit_code(0, alert_delivered=False) == EXIT_ALERT_FAILED
    assert exit_code(EXIT_ISSUES, alert_delivered=False) == EXIT_ALERT_FAILED
    assert exit_code(EXIT_RESTORED, alert_delivered=False) == EXIT_RESTORED
    assert exit_code(EXIT_UNPROTECTED, alert_delivered=False) == EXIT_UNPROTECTED
    assert exit_code(EXIT_ISSUES, alert_delivered=True) == EXIT_ISSUES
    assert exit_code(0, alert_delivered=None) == 0


# ---- version binding (ADR 0011): the monitor's maintenance refuses, restoration proceeds

from scripts.protection_monitor import EXIT_ALERT_FAILED, EXIT_VERSION_BINDING, run_monitor  # noqa: E402

CONVERT_BOOK = ([position("AMD", price="101")], [stop("s1", "AMD", "stop", "90")])


def monitor(monkeypatch, version, outcome=None, book=CONVERT_BOOK, delivered=True, **kw):
    if version is None:
        monkeypatch.delenv("STRATEGY_VERSION")
    else:
        monkeypatch.setenv("STRATEGY_VERSION", version)
    positions, orders = book
    seen = {"replace": [], "sent": []}

    def replace(order_id, trail_percent=None, stop_price=None, binding=None):
        seen["replace"].append((order_id, binding))
        raise outcome or Outcome(EXIT_OK, "replaced")

    def send(report):
        seen["sent"].append(report)
        return delivered

    report = run_monitor(NOW, read=lambda cmd, *a: positions if cmd == "positions" else orders,
                         replace=replace, send=send, email=True, **kw)
    return report, seen


def test_bound_monitor_is_unchanged(monkeypatch):
    report, seen = monitor(monkeypatch, "v1")
    assert report["exit"] == 0 and report["version_binding"]["error"] is None
    assert report["strategy_version"] == "v1" and seen["replace"][0][1].error is None


@pytest.mark.parametrize("version", [None, "", "v1 ", "v2"])
def test_unbound_monitor_plans_under_the_approved_version_and_fails_loudly(monkeypatch, version):
    refused = Outcome(EXIT_REFUSED, "version_binding_refused", reason="STRATEGY_VERSION ...")
    report, seen = monitor(monkeypatch, version, outcome=refused)
    assert report["exit"] == EXIT_VERSION_BINDING
    assert report["strategy_version"] == "v1" and report["version_binding"]["approved"] == APPROVED
    assert report["version_binding"]["error"] and seen["replace"][0][1].error  # replace_stop decides restoration
    assert seen["sent"], "a binding failure always alerts"


def test_unbound_monitor_alerts_even_with_nothing_to_do(monkeypatch):
    covered = ([position("AMD")], [stop("s1", "AMD", "trailing_stop", "90", trail="10")])
    report, seen = monitor(monkeypatch, None, book=covered)
    assert report["exit"] == EXIT_VERSION_BINDING and seen["replace"] == [] and seen["sent"]


def test_unbound_dry_run_still_reports_the_binding(monkeypatch):
    report, seen = monitor(monkeypatch, None, dry_run=True)
    assert report["exit"] == EXIT_VERSION_BINDING and seen["replace"] == []


def test_incident_outranks_the_binding_code(monkeypatch):
    report, _ = monitor(monkeypatch, None, outcome=Outcome(EXIT_UNPROTECTED, "replacement_and_restore_failed"))
    assert report["exit"] == EXIT_UNPROTECTED


def test_lost_alert_on_an_unbound_run_is_named(monkeypatch):
    report, _ = monitor(monkeypatch, None, delivered=False)
    assert report["exit"] == EXIT_ALERT_FAILED


def test_unreadable_pins_still_verify_coverage_but_act_on_nothing(monkeypatch, tmp_path):
    from scripts import strategy_version
    monkeypatch.setattr(strategy_version, "PINS_FILE", tmp_path / "missing.json")
    naked = ([position("AMD")], [])
    report, seen = monitor(monkeypatch, "v1", book=naked)
    assert report["exit"] == EXIT_VERSION_BINDING and seen["replace"] == []
    assert report["coverage"]["ok"] is False and report["strategy_version"] is None
    assert "pins unreadable" in report["version_binding"]["error"]


def test_binding_failure_is_in_the_alert_text():
    import subprocess
    from scripts.protection_monitor import notify
    sent = []
    report = {"observed_at": "t", "exit": 6, "coverage": {"issues": []}, "results": [], "holds": [],
              "standing": [], "version_binding": {"approved": APPROVED, "error": "STRATEGY_VERSION is unset"}}
    notify(report, run=lambda cmd, **kw: sent.append(cmd[-1]) or subprocess.CompletedProcess(cmd, 0))
    assert "VERSION BINDING" in sent[0] and "unset" in sent[0]

"""Resumable stop replacement (#2 floor across cancel, #3 naked window) and
bounded order-history reads (#1), all offline."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import coordinator
from tests.store_support import fresh_stores, intent_lines, make_origin, writer_store

from risk_engine import PortfolioState, Position
from scripts import validate_order
from scripts.replace_stop import (EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_RESTORED,
                                  EXIT_UNPROTECTED, EXIT_USAGE, Outcome, replace_stop)
from scripts.validate_mutation import validate_mutation
from scripts.strategy_version import PINS_FILE

ROOT = Path(__file__).resolve().parents[1]
OLD = "11111111-2222-3333-4444-555555555555"
NOW = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
APPROVED = json.loads(PINS_FILE.read_text())["active"]  # the live approved version



@pytest.fixture(autouse=True)
def coordinated(tmp_path, monkeypatch):
    """Each replacement is a coordinated action against its own empty store;
    the store's part is in tests/test_coordinated_helpers.py."""
    monkeypatch.setattr(coordinator, "open_store", fresh_stores(tmp_path))

class FakeBroker:
    """Order state machine. `cancel_to` is what a cancel request turns the old stop into."""

    def __init__(self, status="new", stop_price="117", cancel_to="canceled", replacement="new",
                 restore="new", fail_reads_after_cancel=False, cancel_ok=True):
        self.orders = {OLD: {"id": OLD, "symbol": "AAPL", "side": "sell", "type": "trailing_stop",
                             "qty": "100", "filled_qty": "0", "status": status, "stop_price": stop_price,
                             "time_in_force": "gtc", "expires_at": "2026-12-18T21:00:00Z"}}
        self.by_client = {}
        self.positions = [{"symbol": "AAPL", "qty": "100", "market_value": "12000"}]
        self.cancel_to, self.replacement, self.restore = cancel_to, replacement, restore
        self.fail_reads_after_cancel, self.cancel_ok = fail_reads_after_cancel, cancel_ok
        self.calls = []

    def read(self, command, arg=None):
        if self.fail_reads_after_cancel and ("run", "cancel", OLD) in self.calls:
            raise SystemExit(4)
        if command == "order-info":
            return self.orders[arg]
        if command == "order-by-client":
            return self.by_client.get(arg)
        if command == "positions":
            return self.positions
        if command == "orders":
            return [o for o in self.orders.values()]
        raise AssertionError(command)

    def run(self, command, arg):
        self.calls.append(("run", command, arg))
        if command == "cancel":
            if not self.cancel_ok:
                return False, "422", "", "order is not cancelable"
            self.orders[OLD]["status"] = self.cancel_to
            return True, "204", "", ""
        body = json.loads(arg)
        outcome = self.replacement if body["client_order_id"].startswith("rs-") else self.restore
        if outcome is None:
            return False, "422", "", "rejected"
        self.by_client[body["client_order_id"]] = {**body, "status": outcome}
        return True, "200", "{}", ""

    def check(self, command, body):
        self.calls.append(("check", command, body))

    def posted(self):
        return [json.loads(c[2]) for c in self.calls if c[:2] == ("run", "order")]


def go(broker, check=None, trail="7", stop=None):
    with pytest.raises(Outcome) as info:
        replace_stop(OLD, None if stop else trail, stop, read=broker.read, run=broker.run, check=check or broker.check,
                     sleep=lambda _: None, polls=5, now=NOW)
    return info.value


# --- Exit codes derive from broker coverage, not from what this process did (#95) ---


def refusing(*_a):
    raise ValueError("stop_never_lowered")


def test_refusal_while_old_stop_verifiably_protects_is_exit_3():
    out = go(FakeBroker(), check=refusing)
    assert (out.code, out.state) == (EXIT_REFUSED, "refused")


def test_refusal_while_old_stop_cannot_certify_coverage_is_an_incident():
    for order in ({"status": "held"}, {"qty": "60"}, {"expires_at": "2026-09-01T00:00:00Z"}):
        b = FakeBroker()
        b.orders[OLD].update(order)
        out = go(b, check=refusing)
        assert (out.code, out.state) == (EXIT_UNPROTECTED, "refused_position_unprotected"), order
        assert b.posted() == [] and out.detail["coverage"]["ok"] is False


def test_expired_old_stop_on_a_held_position_is_an_incident_not_usage():
    b = FakeBroker(status="expired")
    out = go(b)
    assert (out.code, out.state) == (EXIT_UNPROTECTED, "old_stop_gone_position_unprotected")
    flat = FakeBroker(status="expired")
    flat.positions = []
    assert go(flat).code == EXIT_USAGE  # nothing held: a stale order id is a usage error


def test_read_failure_in_preflight_on_an_uncovered_position_is_an_incident():
    b = FakeBroker()
    b.orders[OLD]["status"] = "held"
    out = go(b, check=lambda *_a: (_ for _ in ()).throw(SystemExit(4)))
    assert (out.code, out.state) == (EXIT_UNPROTECTED, "broker_state_unavailable_position_unprotected")
    covered = go(FakeBroker(), check=lambda *_a: (_ for _ in ()).throw(SystemExit(4)))
    assert (covered.code, covered.state) == (EXIT_NO_STATE, "broker_state_unavailable")


def test_happy_path_validates_before_cancel_then_replaces():
    b = FakeBroker()
    out = go(b)
    assert (out.code, out.state) == (EXIT_OK, "replaced")
    kinds = [c[:2] for c in b.calls]
    assert kinds == [("check", "order"), ("run", "cancel"), ("run", "order")]
    assert b.posted()[0]["client_order_id"] == "rs-" + OLD
    assert b.posted()[0]["trail_percent"] == "7"


def test_fixed_renewal_uses_the_same_resumable_path():
    b = FakeBroker(status="new")
    out = go(b, stop="117.00")
    assert out.state == "replaced"
    body = b.posted()[0]
    assert (body["type"], body["stop_price"]) == ("stop", "117.00") and "trail_percent" not in body


def test_preflight_refusal_leaves_old_stop_untouched():
    b = FakeBroker()

    def refuse(*_):
        raise ValueError("stop_never_lowered")
    out = go(b, check=refuse)
    assert (out.code, out.state) == (EXIT_REFUSED, "refused")
    assert b.calls == [] and b.orders[OLD]["status"] == "new"


def test_rerun_after_crash_post_cancel_resumes_without_duplicates():
    b = FakeBroker(status="canceled")  # a previous run died after cancel
    out = go(b)
    assert out.state == "replaced"
    assert [c[1] for c in b.calls] == ["order"], "no second cancel, no preflight on a canceled stop"
    again = go(b)
    assert again.state == "already_replaced" and len(b.posted()) == 1


def test_stop_filled_during_cancel_places_nothing():
    b = FakeBroker(cancel_to="filled")
    assert go(b).state == "old_stop_filled"
    assert b.posted() == []


def test_failed_replacement_restores_exact_prior_level():
    b = FakeBroker(replacement=None)
    out = go(b)
    assert (out.code, out.state) == (EXIT_RESTORED, "replacement_failed_old_level_restored")
    restore = b.posted()[-1]
    assert restore["type"] == "stop" and restore["stop_price"] == "117"
    assert restore["client_order_id"] == "rr-" + OLD
    assert go(b).state == "already_restored"


def test_total_failure_is_reported_unprotected():
    out = go(FakeBroker(replacement=None, restore=None))
    assert (out.code, out.state) == (EXIT_UNPROTECTED, "replacement_and_restore_failed")


def test_unconfirmed_cancel_never_submits():
    b = FakeBroker(cancel_to="pending_cancel")
    out = go(b)
    assert (out.code, out.state) == (EXIT_UNPROTECTED, "cancel_unconfirmed")
    assert b.posted() == []


def test_broker_refused_cancel_reports_old_stop_still_protecting():
    b = FakeBroker(cancel_ok=False)
    out = go(b)
    assert (out.code, out.state) == (EXIT_REFUSED, "cancel_rejected_old_stop_still_protects")
    assert b.posted() == []


def test_accepted_cancel_still_open_after_full_window_is_an_incident_not_still_protects():
    # The broker took the cancel (204) but the order still reads open: it may cancel
    # a moment after we stop looking. Never report "still protects"; poll the whole
    # window, then exit 8 so the rerun resumes.
    b = FakeBroker(cancel_to="new")
    out = go(b)
    assert (out.code, out.state) == (EXIT_UNPROTECTED, "cancel_accepted_but_unconfirmed_rerun")
    assert b.posted() == []


def test_read_failure_before_cancel_is_harmless_after_cancel_is_incident():
    class Down(FakeBroker):
        def read(self, *_):
            raise SystemExit(4)
    assert go(Down()).code == EXIT_NO_STATE
    assert go(FakeBroker(fail_reads_after_cancel=True)).code == EXIT_UNPROTECTED


# ---- mutation-layer floor survives cancellation (#2) -------------------------

def trail_body(**extra):
    return json.dumps({"symbol": "AAPL", "qty": "100", "side": "sell", "type": "trailing_stop",
                       "time_in_force": "gtc", "trail_percent": "5", **extra})


def snapshot(old_status="canceled", opens=(), closed=()):
    return {
        ("asset", "AAPL"): {"symbol": "AAPL", "class": "us_equity", "status": "active", "tradable": True},
        ("orders", "open"): list(opens),
        ("orders", "closed", "2026-09-17T15:45:00Z"): list(closed),
        ("order-info", OLD): {"id": OLD, "symbol": "AAPL", "side": "sell", "type": "trailing_stop",
                              "status": old_status, "stop_price": "117"},
    }


def mutation(body, snap):
    validate_mutation("order", body, read=lambda *a: snap[a], now=NOW,
                      portfolio=PortfolioState(equity="100000", cash="88000", is_paper=True, reservations=(),
                                               positions=(Position("AAPL", "100", "12000"),)))


def test_replacement_cannot_lower_a_canceled_stops_floor():
    # HWM 130 → old stop 117; price 120 → 5% trail starts at 114.
    with pytest.raises(ValueError, match="stop_never_lowered"):
        mutation(trail_body(client_order_id="rs-" + OLD), snapshot())


def test_manual_cancel_then_order_still_sees_the_recent_floor():
    recent = {"symbol": "AAPL", "side": "sell", "type": "trailing_stop", "status": "canceled",
              "stop_price": "117"}
    with pytest.raises(ValueError, match="stop_never_lowered"):
        mutation(trail_body(), snapshot(closed=[recent]))


def test_replacement_requires_confirmed_cancel():
    with pytest.raises(ValueError, match="confirmed canceled"):
        mutation(trail_body(client_order_id="rs-" + OLD), snapshot(old_status="pending_cancel"))


def test_replacement_at_or_above_floor_is_allowed():
    snap = snapshot()
    snap[("order-info", OLD)]["stop_price"] = "110"  # 5% trail at 120 starts at 114
    mutation(trail_body(client_order_id="rs-" + OLD), snap)


def test_restore_must_match_exact_level_but_skips_distance_rule():
    def restore(level):
        return json.dumps({"symbol": "AAPL", "qty": "100", "side": "sell", "type": "stop",
                           "time_in_force": "gtc", "stop_price": level, "client_order_id": "rr-" + OLD})
    snap = snapshot()
    snap[("order-info", OLD)]["stop_price"] = "118.5"  # within 3% of 120: restore still allowed
    mutation(restore("118.5"), snap)
    with pytest.raises(ValueError, match="exact level"):
        mutation(restore("110"), snap)


# ---- bounded order history (#1) ---------------------------------------------

def test_weekly_trade_count_requests_a_bounded_window(monkeypatch):
    seen = []
    monkeypatch.setattr(validate_order, "adapter", lambda *a: seen.append(a) or [])
    assert validate_order.trades_this_week(datetime(2026, 9, 17, 15, tzinfo=timezone.utc)) == 0
    assert seen == [("orders", "closed", "2026-09-07T00:00:00Z")]


def _wrapper(tmp_path, *args):
    (tmp_path / "scripts").mkdir()
    for name in ("alpaca.sh",):
        (tmp_path / "scripts" / name).write_text((ROOT / "scripts" / name).read_text())
    (tmp_path / "scripts" / "_env.sh").write_text(":\n")
    curl = tmp_path / "curl"
    curl.write_text(f"#!{sys.executable}\n" + '''
import os, sys
from pathlib import Path
a = sys.argv[1:]
open(os.environ["URLS"], "a").write(a[-1] + "\\n")
code = "404" if "missing" in a[-1] else "200"
if "-o" in a:
    Path(a[a.index("-o") + 1]).write_text('{"id": "x"}')
    print(code, end="")
else:
    print("[]")
''')
    curl.chmod(0o700)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "ALPACA_API_KEY": "offline",
           "ALPACA_SECRET_KEY": "offline", "URLS": str(tmp_path / "urls")}
    result = subprocess.run(["/bin/bash", str(tmp_path / "scripts/alpaca.sh"), *args],
                            env=env, text=True, capture_output=True, timeout=10)
    urls = (tmp_path / "urls").read_text().split() if (tmp_path / "urls").exists() else []
    return result, urls


def test_wrapper_passes_after_window(tmp_path):
    result, urls = _wrapper(tmp_path, "orders", "closed", "2026-09-07T00:00:00Z")
    assert result.returncode == 0, result.stderr
    assert urls == ["https://paper-api.alpaca.markets/v2/orders?status=closed&limit=500&after=2026-09-07T00:00:00Z"]


@pytest.mark.parametrize("args", [("orders", "closed", "2026-09-07; rm"), ("orders", "bogus")])
def test_wrapper_rejects_malformed_order_queries(tmp_path, args):
    result, urls = _wrapper(tmp_path, *args)
    assert result.returncode == 2 and urls == []


def test_order_by_client_maps_404_to_null(tmp_path):
    result, _ = _wrapper(tmp_path, "order-by-client", "rs-missing")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is None


# ---- end-to-end: replace_stop.py -> alpaca.sh -> validate_mutation -> fake broker

FAKE_BROKER = r'''
import json, os, sys, uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse, parse_qs
a = sys.argv[1:]
url = urlparse(a[-1]); path = url.path.removeprefix("/v2"); q = parse_qs(url.query)
state_file = Path(os.environ["BROKER_STATE"]); st = json.loads(state_file.read_text())
method = a[a.index("-X") + 1] if "-X" in a else "GET"
code, data = 200, None
if path == "/account":
    data = {"account_number": "PATEST000001", "equity": "100000", "cash": "88000"}
elif path == "/positions":
    data = [{"symbol": "AAPL", "qty": "100", "market_value": "12000"}]
elif path == "/assets/AAPL":
    data = {"symbol": "AAPL", "class": "us_equity", "status": "active", "tradable": True}
elif path == "/orders:by_client_order_id":
    hits = [o for o in st["orders"] if o.get("client_order_id") == q["client_order_id"][0]]
    code, data = (200, hits[0]) if hits else (404, {"message": "not found"})
elif path == "/orders" and method == "GET":
    want = q["status"][0]
    data = [o for o in st["orders"] if (o["status"] in ("new", "pending_cancel")) == (want == "open")]
elif path == "/orders" and method == "POST":
    body = json.loads(a[a.index("-d") + 1])
    if os.environ.get("REJECT_TRAIL") and body["type"] == "trailing_stop":
        code, data = 422, {"message": "rejected"}
    else:
        level = body.get("stop_price") or str(Decimal("120") * (1 - Decimal(body["trail_percent"]) / 100))
        data = {**body, "id": str(uuid.uuid4()), "status": "new", "stop_price": level, "filled_qty": "0"}
        st["orders"].append(data)
elif path.startswith("/orders/") and method == "DELETE":
    next(o for o in st["orders"] if o["id"] == path.split("/")[-1])["status"] = "canceled"
    code, data = 204, {}
elif path.startswith("/orders/"):
    data = next(o for o in st["orders"] if o["id"] == path.split("/")[-1])
else:
    raise AssertionError("unexpected " + method + " " + a[-1])
state_file.write_text(json.dumps(st))
out = json.dumps(data)
if "-o" in a:
    Path(a[a.index("-o") + 1]).write_text(out); print(code, end="")
else:
    if code >= 400:
        sys.exit(22)
    print(out)
'''


def run_e2e(tmp_path, old_stop, trail, old_status="new", **env_extra):
    import os
    import shutil
    for name in ("scripts", "risk_engine", "ledger"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("docs/rulebook-pins.json", "memory/TRADING-STRATEGY.md"):
        (tmp_path / name).parent.mkdir(exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / "scripts" / "_env.sh").write_text(":\n")
    # The alert channel: record instead of calling Resend.
    (tmp_path / "scripts" / "email.sh").write_text(f'printf "%s" "$1" > "{tmp_path}/alert.txt"\n')
    (tmp_path / "scripts" / "accounts.json").write_text(
        '{"production": {"account_number": "PATEST000001", "id": null}, "drill": {"account_number": null, "id": null}}')
    curl = tmp_path / "bin" / "curl"
    curl.parent.mkdir()
    curl.write_text(f"#!{sys.executable}\n" + FAKE_BROKER)
    curl.chmod(0o700)
    state = tmp_path / "broker.json"
    state.write_text(json.dumps({"orders": [
        {"id": OLD, "symbol": "AAPL", "side": "sell", "type": "trailing_stop", "qty": "100",
         "filled_qty": "0", "status": old_status, "stop_price": old_stop, "trail_percent": "10",
         "time_in_force": "gtc", "expires_at": "2099-01-01T00:00:00Z"}]}))
    env = {"PATH": f"{curl.parent}:{Path(sys.executable).parent}:/usr/bin:/bin",
           "ALPACA_API_KEY": "offline", "ALPACA_SECRET_KEY": "offline",
           "BROKER_STATE": str(state), "TMPDIR": str(tmp_path),
           "STRATEGY_VERSION": os.environ["STRATEGY_VERSION"],
           "TRADING_STATE_REPO": str(writer_store(tmp_path, origin := make_origin(tmp_path), "state").repo),
           **env_extra}
    env = {k: v for k, v in env.items() if v is not None}
    proc = subprocess.run([sys.executable, str(tmp_path / "scripts/replace_stop.py"),
                           "--order-id", OLD, "--trail-percent", trail],
                          env=env, text=True, capture_output=True, timeout=60)
    proc.origin = origin
    return proc, json.loads(state.read_text())["orders"]


def test_e2e_tighten_replaces_through_real_wrapper(tmp_path):
    proc, orders = run_e2e(tmp_path, old_stop="108", trail="5")  # 5% at 120 = 114 >= 108
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["state"] == "replaced"
    assert [o["status"] for o in orders] == ["canceled", "new"]
    assert orders[1]["client_order_id"] == "rs-" + OLD
    # One coordinated action: recorded before the cancel, complete once the replacement rests.
    assert [e["state"] for e in intent_lines(proc.origin, "rs-" + OLD)] == ["recorded", "complete"]


def test_e2e_lowering_refused_before_cancel(tmp_path):
    proc, orders = run_e2e(tmp_path, old_stop="117", trail="5")  # HWM 130 floor
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "stop_never_lowered" in proc.stdout
    assert [o["status"] for o in orders] == ["new"], "old stop must remain untouched"


def test_e2e_rejected_replacement_restores_old_level(tmp_path):
    proc, orders = run_e2e(tmp_path, old_stop="108", trail="5", REJECT_TRAIL="1")
    assert proc.returncode == 7, proc.stdout + proc.stderr
    assert [(o["status"], o["type"], o["stop_price"]) for o in orders] == [
        ("canceled", "trailing_stop", "108"), ("new", "stop", "108")]


# ---- version binding (ADR 0011): only restoration proceeds, under the approved version

def unbound(monkeypatch):
    monkeypatch.delenv("STRATEGY_VERSION")


def test_unbound_gate_allows_replacement_after_confirmed_cancel_on_a_naked_position(monkeypatch, capsys):
    unbound(monkeypatch)
    snap = snapshot()
    snap[("order-info", OLD)]["stop_price"] = "110"
    mutation(trail_body(client_order_id="rs-" + OLD), snap)
    assert "VERSION BINDING EXCEPTION" in capsys.readouterr().err


def test_unbound_gate_allows_exact_restore(monkeypatch):
    unbound(monkeypatch)
    mutation(json.dumps({"symbol": "AAPL", "qty": "100", "side": "sell", "type": "stop", "time_in_force": "gtc",
                         "stop_price": "117", "client_order_id": "rr-" + OLD}), snapshot())


def test_unbound_gate_still_applies_the_approved_versions_rules(monkeypatch):
    unbound(monkeypatch)
    with pytest.raises(ValueError, match="stop_never_lowered"):
        mutation(trail_body(client_order_id="rs-" + OLD), snapshot())
    with pytest.raises(ValueError, match="protective trail"):
        mutation(trail_body(client_order_id="rs-" + OLD, trail_percent="12"), snapshot())


def test_unbound_gate_refuses_restoration_while_another_stop_rests(monkeypatch):
    unbound(monkeypatch)
    resting = {"symbol": "AAPL", "side": "sell", "type": "stop", "status": "new", "stop_price": "100"}
    with pytest.raises(ValueError, match="still resting"):
        mutation(trail_body(client_order_id="rs-" + OLD), snapshot(opens=[resting]))


def test_unbound_gate_refuses_a_stop_without_a_restoration_id(monkeypatch):
    unbound(monkeypatch)
    snap = snapshot()
    snap[("order-info", OLD)]["stop_price"] = "110"
    with pytest.raises(ValueError, match="version binding"):
        mutation(trail_body(), snap)


@pytest.mark.parametrize("version", [None, "", "v2", "V1"])
def test_unbound_replace_refuses_before_any_cancel(monkeypatch, version):
    monkeypatch.setenv("STRATEGY_VERSION", version) if version is not None else unbound(monkeypatch)
    b = FakeBroker()
    out = go(b)
    assert (out.code, out.state) == (EXIT_REFUSED, "version_binding_refused")
    assert "STRATEGY_VERSION" in out.detail["reason"] and b.calls == []


def test_unbound_replace_on_an_uncovered_resting_stop_is_an_incident(monkeypatch):
    unbound(monkeypatch)
    b = FakeBroker()
    b.orders[OLD]["qty"] = "60"  # short: the resting stop does not certify coverage
    out = go(b)
    assert (out.code, out.state) == (EXIT_UNPROTECTED, "version_binding_refused_position_unprotected")
    assert b.calls == []


def test_unbound_rerun_after_cancel_restores_protection_under_the_approved_version(monkeypatch):
    unbound(monkeypatch)
    b = FakeBroker(status="canceled")  # an earlier run canceled and died: the position is naked
    out = go(b)
    assert (out.code, out.state) == (EXIT_OK, "replaced")
    assert [c[1] for c in b.calls] == ["order"], "never a cancel under a failed binding"
    exc = out.detail["version_exception"]
    assert exc["approved"] == APPROVED and exc["engine"] == "v1" and "unset" in exc["error"]


def test_unbound_rerun_falls_back_to_exact_restore(monkeypatch):
    unbound(monkeypatch)
    out = go(FakeBroker(status="canceled", replacement=None))
    assert (out.code, out.state) == (EXIT_RESTORED, "replacement_failed_old_level_restored")
    assert "version_exception" in out.detail


def test_unbound_rerun_with_nothing_held_refuses(monkeypatch):
    unbound(monkeypatch)
    b = FakeBroker(status="canceled")
    b.positions = []
    out = go(b)
    assert (out.code, out.state) == (EXIT_REFUSED, "version_binding_refused") and b.calls == []


def test_unbound_read_only_resume_still_reports(monkeypatch):
    unbound(monkeypatch)
    b = FakeBroker(status="canceled")
    b.by_client["rs-" + OLD] = {"status": "new"}
    assert go(b).state == "already_replaced"


def test_unreadable_pins_is_a_usage_error_before_broker_reads(monkeypatch, tmp_path):
    from scripts import strategy_version
    monkeypatch.setattr(strategy_version, "PINS_FILE", tmp_path / "missing.json")
    out = go(FakeBroker(), check=lambda *a: pytest.fail("no preflight"))
    assert (out.code, out.state) == (EXIT_USAGE, "version_binding_unreadable")


def test_e2e_unbound_runner_never_cancels(tmp_path):
    proc, orders = run_e2e(tmp_path, old_stop="108", trail="5", STRATEGY_VERSION=None)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["state"] == "version_binding_refused"
    assert [o["status"] for o in orders] == ["new"]
    assert not (tmp_path / "alert.txt").exists()


def test_e2e_unbound_restoration_proceeds_through_the_gate_and_alerts(tmp_path):
    proc, orders = run_e2e(tmp_path, old_stop="108", trail="5", old_status="canceled", STRATEGY_VERSION="v2")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["state"] == "replaced" and report["alert_delivered"] is True
    assert [(o["status"], o.get("client_order_id")) for o in orders] == [("canceled", None), ("new", "rs-" + OLD)]
    alert = (tmp_path / "alert.txt").read_text()
    assert "VERSION BINDING INCIDENT" in alert and "AAPL" in alert and APPROVED in alert

"""Resumable stop replacement (#2 floor across cancel, #3 naked window) and
bounded order-history reads (#1), all offline."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from risk_engine import PortfolioState, Position
from scripts import validate_order
from scripts.replace_stop import (EXIT_NO_STATE, EXIT_OK, EXIT_REFUSED, EXIT_RESTORED,
                                  EXIT_UNPROTECTED, Outcome, replace_stop)
from scripts.validate_mutation import validate_mutation

ROOT = Path(__file__).resolve().parents[1]
OLD = "11111111-2222-3333-4444-555555555555"
NOW = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)


class FakeBroker:
    """Order state machine. `cancel_to` is what a cancel request turns the old stop into."""

    def __init__(self, status="new", stop_price="117", cancel_to="canceled", replacement="new",
                 restore="new", fail_reads_after_cancel=False):
        self.orders = {OLD: {"id": OLD, "symbol": "AAPL", "side": "sell", "type": "trailing_stop",
                             "qty": "100", "filled_qty": "0", "status": status, "stop_price": stop_price}}
        self.by_client = {}
        self.cancel_to, self.replacement, self.restore = cancel_to, replacement, restore
        self.fail_reads_after_cancel = fail_reads_after_cancel
        self.calls = []

    def read(self, command, arg):
        if self.fail_reads_after_cancel and ("run", "cancel", OLD) in self.calls:
            raise SystemExit(4)
        if command == "order-info":
            return self.orders[arg]
        if command == "order-by-client":
            return self.by_client.get(arg)
        raise AssertionError(command)

    def run(self, command, arg):
        self.calls.append(("run", command, arg))
        if command == "cancel":
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
                     sleep=lambda _: None, polls=5)
    return info.value


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


def test_rejected_cancel_reports_old_stop_still_protecting():
    b = FakeBroker(cancel_to="new")
    out = go(b)
    assert (out.code, out.state) == (EXIT_REFUSED, "cancel_rejected_old_stop_still_protects")
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
                      portfolio=PortfolioState(equity="100000", cash="88000", is_paper=True,
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
    data = {"equity": "100000", "cash": "88000"}
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


def run_e2e(tmp_path, old_stop, trail, **env_extra):
    import shutil
    for name in ("scripts", "risk_engine", "ledger"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "scripts" / "_env.sh").write_text(":\n")
    curl = tmp_path / "bin" / "curl"
    curl.parent.mkdir()
    curl.write_text(f"#!{sys.executable}\n" + FAKE_BROKER)
    curl.chmod(0o700)
    state = tmp_path / "broker.json"
    state.write_text(json.dumps({"orders": [
        {"id": OLD, "symbol": "AAPL", "side": "sell", "type": "trailing_stop", "qty": "100",
         "filled_qty": "0", "status": "new", "stop_price": old_stop, "trail_percent": "10",
         "time_in_force": "gtc"}]}))
    env = {"PATH": f"{curl.parent}:{Path(sys.executable).parent}:/usr/bin:/bin",
           "ALPACA_API_KEY": "offline", "ALPACA_SECRET_KEY": "offline",
           "BROKER_STATE": str(state), "TMPDIR": str(tmp_path), **env_extra}
    proc = subprocess.run([sys.executable, str(tmp_path / "scripts/replace_stop.py"),
                           "--order-id", OLD, "--trail-percent", trail],
                          env=env, text=True, capture_output=True, timeout=60)
    return proc, json.loads(state.read_text())["orders"]


def test_e2e_tighten_replaces_through_real_wrapper(tmp_path):
    proc, orders = run_e2e(tmp_path, old_stop="108", trail="5")  # 5% at 120 = 114 >= 108
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["state"] == "replaced"
    assert [o["status"] for o in orders] == ["canceled", "new"]
    assert orders[1]["client_order_id"] == "rs-" + OLD


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

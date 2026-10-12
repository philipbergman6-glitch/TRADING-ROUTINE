"""Account profiles: production vs the isolated drill paper account.

Isolation between two paper accounts is key-only (research 0010), so the
wrapper must (1) refuse when both key pairs are present in one invocation,
(2) use the pair the selected profile names, and (3) compare the broker's
account_number with the pinned one before any write.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.account_pin import check_pin, load_pin
from scripts.heartbeat import resolve_credentials

ROOT = Path(__file__).resolve().parents[1]
PINS = {"production": {"account_number": "PAPROD000001", "id": "11111111-1111-1111-1111-111111111111"},
        "drill": {"account_number": "PADRILL00001", "id": "22222222-2222-2222-2222-222222222222"}}

FAKE_CURL = '''
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
url = a[-1]
headers = [a[i + 1] for i, x in enumerate(a) if x == "-H"]
key = next(h.split(": ", 1)[1] for h in headers if h.startswith("APCA-API-KEY-ID"))
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"key": key, "url": url, "post": "-X" in a}) + "\\n")
by_key = json.loads(os.environ["ACCOUNT_BY_KEY"])
if url.endswith("/account"):
    data = {"account_number": by_key[key], "equity": "100000", "cash": "100000"}
elif "-X" in a:
    data = {"id": "paper-order", "status": "accepted"}
elif url.endswith("/positions") or "/orders?" in url:
    data = []
elif "/assets/" in url:
    data = {"symbol": "AAPL", "class": "us_equity", "status": "active", "tradable": True}
elif "/quotes/latest" in url:
    from datetime import datetime, timezone
    data = {"quote": {"ap": 100.0, "t": datetime.now(timezone.utc).isoformat()}}
else:
    raise AssertionError("unexpected " + url)
out = json.dumps(data)
if "-o" in a:
    Path(a[a.index("-o") + 1]).write_text(out)
    print("200", end="")
else:
    print(out)
'''


@pytest.fixture
def wrapper(tmp_path):
    for name in ("scripts", "risk_engine", "ledger"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "scripts" / "_env.sh").write_text(":\n")
    (tmp_path / "scripts" / "accounts.json").write_text(json.dumps(PINS))
    curl = tmp_path / "curl"
    curl.write_text(f"#!{sys.executable}\n" + FAKE_CURL)
    curl.chmod(0o700)
    calls = tmp_path / "calls"
    base = {"PATH": f"{tmp_path}:{Path(sys.executable).parent}:/usr/bin:/bin",
            "CALLS": str(calls),
            "ACCOUNT_BY_KEY": json.dumps({"prod-key": "PAPROD000001", "drill-key": "PADRILL00001"})}

    def run(*argv, **env):
        r = subprocess.run(["/bin/bash", str(tmp_path / "scripts/alpaca.sh"), *argv],
                           env={**base, **env}, text=True, capture_output=True, timeout=15)
        made = [json.loads(l) for l in calls.read_text().splitlines()] if calls.exists() else []
        return r, made
    return run


PROD = {"ALPACA_API_KEY": "prod-key", "ALPACA_SECRET_KEY": "prod-sec"}
DRILL = {"DRILL_ALPACA_API_KEY": "drill-key", "DRILL_ALPACA_SECRET_KEY": "drill-sec"}
ORDER = json.dumps({"symbol": "AAPL", "qty": "100", "side": "buy", "type": "market",
                    "order_class": "oto", "time_in_force": "gtc", "stop_loss": {"stop_price": "90"}})


# --- profile selection --------------------------------------------------------

def test_default_profile_is_production_and_uses_alpaca_keys(wrapper):
    r, calls = wrapper("account", **PROD)
    assert r.returncode == 0, r.stderr
    assert calls[0]["key"] == "prod-key"


def test_drill_profile_uses_drill_keys(wrapper):
    r, calls = wrapper("account", ALPACA_PROFILE="drill", **DRILL)
    assert r.returncode == 0, r.stderr
    assert calls[0]["key"] == "drill-key"


def test_account_flag_selects_drill_profile(wrapper):
    r, calls = wrapper("--account", "drill", "account", **DRILL)
    assert r.returncode == 0, r.stderr
    assert calls[0]["key"] == "drill-key"


def test_both_key_pairs_present_is_refused_before_any_call(wrapper):
    r, calls = wrapper("account", **PROD, **DRILL)
    assert r.returncode == 6, r.stderr
    assert "both" in r.stderr.lower() and calls == []
    assert "prod-sec" not in r.stderr and "drill-sec" not in r.stderr


def test_both_pairs_refused_even_under_drill_profile(wrapper):
    r, calls = wrapper("account", ALPACA_PROFILE="drill", **PROD, **DRILL)
    assert r.returncode == 6 and calls == []


def test_drill_profile_without_drill_keys_is_refused(wrapper):
    r, calls = wrapper("account", ALPACA_PROFILE="drill", **PROD)
    assert r.returncode == 6, r.stderr
    assert "DRILL_ALPACA_API_KEY" in r.stderr and calls == []


def test_unknown_profile_is_refused(wrapper):
    r, calls = wrapper("account", ALPACA_PROFILE="live", **PROD)
    assert r.returncode == 6 and calls == []


def test_flag_and_env_disagreeing_is_refused(wrapper):
    r, calls = wrapper("--account", "production", "account", ALPACA_PROFILE="drill", **DRILL)
    assert r.returncode == 6 and calls == []


def test_account_flag_without_value_is_usage_error(wrapper):
    r, calls = wrapper("--account", **PROD)
    assert r.returncode == 1 and calls == []


# --- pinned account check before any write ------------------------------------

def test_write_is_refused_when_broker_account_differs_from_pin(wrapper):
    wrong = json.dumps({"prod-key": "PAOTHER00001"})
    r, calls = wrapper("order", ORDER, ALPACA_RISK_OK="1", ACCOUNT_BY_KEY=wrong, **PROD)
    assert r.returncode == 8, r.stderr
    assert "PAOTHER00001" in r.stderr and "PAPROD000001" in r.stderr
    assert not any(c["post"] for c in calls)


def test_write_proceeds_when_pin_matches(wrapper):
    r, calls = wrapper("order", ORDER, ALPACA_RISK_OK="1", **PROD)
    assert r.returncode == 0, r.stderr
    assert [c for c in calls if c["post"]][0]["key"] == "prod-key"


def test_drill_keys_pasted_as_production_are_caught(wrapper):
    """The production pair is secretly the drill account's keys: refuse."""
    r, calls = wrapper("order", ORDER, ALPACA_RISK_OK="1",
                       ALPACA_API_KEY="drill-key", ALPACA_SECRET_KEY="drill-sec")
    assert r.returncode == 8 and not any(c["post"] for c in calls)


def test_unpinned_profile_refuses_writes(wrapper, tmp_path):
    pins = {**PINS, "drill": {"account_number": None, "id": None}}
    (tmp_path / "scripts" / "accounts.json").write_text(json.dumps(pins))
    r, calls = wrapper("order", ORDER, ALPACA_PROFILE="drill", ALPACA_RISK_OK="1", **DRILL)
    assert r.returncode == 8, r.stderr
    assert "not pinned" in r.stderr and not any(c["post"] for c in calls)


def test_verify_account_reports_profile_and_number(wrapper):
    r, calls = wrapper("verify-account", ALPACA_PROFILE="drill", **DRILL)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"profile": "drill", "account_number": "PADRILL00001"}


def test_verify_account_fails_on_mismatch(wrapper):
    r, _ = wrapper("verify-account", ACCOUNT_BY_KEY=json.dumps({"prod-key": "PAX"}), **PROD)
    assert r.returncode == 8


def test_pin_check_leaves_status_capture_untouched_on_refusal(wrapper, tmp_path):
    status = tmp_path / "status"
    wrong = json.dumps({"prod-key": "PAOTHER00001"})
    r, _ = wrapper("order", ORDER, ALPACA_RISK_OK="1", ACCOUNT_BY_KEY=wrong,
                   ALPACA_HTTP_STATUS_FILE=str(status), **PROD)
    assert r.returncode == 8
    assert status.read_text() == "000"


# --- scripts/account_pin.py ------------------------------------------------------

def test_committed_pins_name_both_profiles_and_production_is_set():
    pins = json.loads((ROOT / "scripts" / "accounts.json").read_text())
    assert set(pins) == {"production", "drill"}
    assert pins["production"]["account_number"]


def test_load_pin_rejects_unknown_profile(tmp_path):
    f = tmp_path / "accounts.json"
    f.write_text(json.dumps(PINS))
    with pytest.raises(ValueError):
        load_pin("live", f)


def test_check_pin_requires_account_number_in_payload():
    with pytest.raises(ValueError):
        check_pin("PAPROD000001", {"equity": "1"})


def test_check_pin_rejects_mismatch_and_accepts_match():
    assert check_pin("PAPROD000001", {"account_number": "PAPROD000001"}) == "PAPROD000001"
    with pytest.raises(ValueError):
        check_pin("PAPROD000001", {"account_number": "PAX"})


def test_pin_cli_set_writes_pin_and_refuses_malformed_input(tmp_path):
    f = tmp_path / "accounts.json"
    f.write_text(json.dumps({**PINS, "drill": {"account_number": None, "id": None}}))
    ok = subprocess.run([sys.executable, str(ROOT / "scripts/account_pin.py"), "--file", str(f), "set", "drill",
                         "PANEW0000001", "33333333-3333-3333-3333-333333333333"],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(f.read_text())["drill"]["account_number"] == "PANEW0000001"
    bad = subprocess.run([sys.executable, str(ROOT / "scripts/account_pin.py"), "--file", str(f), "set", "drill",
                          "", "33333333-3333-3333-3333-333333333333"],
                         capture_output=True, text=True)
    assert bad.returncode != 0


# --- heartbeat mirrors the same rules -------------------------------------------

def test_heartbeat_resolves_production_by_default():
    assert resolve_credentials({**PROD}) == ("prod-key", "prod-sec")


def test_heartbeat_resolves_drill_profile():
    assert resolve_credentials({"ALPACA_PROFILE": "drill", **DRILL}) == ("drill-key", "drill-sec")


@pytest.mark.parametrize("environ", [
    {**PROD, **DRILL},
    {"ALPACA_PROFILE": "drill", **PROD},
    {"ALPACA_PROFILE": "live", **PROD},
    {"ALPACA_API_KEY": "prod-key"},
])
def test_heartbeat_refuses_ambiguous_or_incomplete_credentials(environ):
    with pytest.raises(RuntimeError):
        resolve_credentials(environ)

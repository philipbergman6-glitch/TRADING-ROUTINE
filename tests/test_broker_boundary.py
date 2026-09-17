"""End-to-end wrapper tests: real validation, fake HTTP transport, no secrets."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def broker(tmp_path):
    for name in ("scripts", "risk_engine", "ledger"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "scripts" / "_env.sh").write_text(":\n")
    curl = tmp_path / "curl"
    curl.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
a = sys.argv[1:]
url = a[-1]
if os.environ.get("FAKE_TRANSPORT_FAILURE"):
    print("000", end="")
    sys.exit(7)
if "-X" in a:
    assert a[a.index("-X") + 1] == "POST"
    body = a[a.index("-d") + 1]
    with open(os.environ["POSTS"], "a") as f:
        f.write(body + "\\n")
    data = {"id": "paper-order", "status": "accepted"}
elif url.endswith("/account"):
    data = {"equity": "100000", "cash": "100000"}
elif url.endswith("/positions") or "/orders?" in url:
    data = []
elif "/assets/" in url:
    data = {"symbol": "AAPL", "class": "us_equity", "status": "active", "tradable": True}
elif "/quotes/latest" in url:
    data = {"quote": {"ap": 100.0, "t": datetime.now(timezone.utc).isoformat()}}
else:
    raise AssertionError("unexpected read " + url)
out = json.dumps(data)
if "-o" in a:
    Path(a[a.index("-o") + 1]).write_text(out)
    print(os.environ.get("FAKE_HTTP_STATUS", "200"), end="")
else:
    print(out)
''')
    curl.chmod(0o700)
    env = {"PATH": f"{tmp_path}:{Path(sys.executable).parent}:/usr/bin:/bin",
           "ALPACA_API_KEY": "offline", "ALPACA_SECRET_KEY": "offline",
           "ALPACA_RISK_OK": "1", "POSTS": str(tmp_path / "posts"),
           "ALPACA_HTTP_STATUS_FILE": str(tmp_path / "status")}
    def run(command, body="", **extra):
        return subprocess.run(["/bin/bash", str(tmp_path / "scripts/alpaca.sh"), command, body],
                              env={**env, **extra}, text=True, capture_output=True, timeout=10)
    return run, tmp_path


def payload(qty="100"):
    return json.dumps({"symbol": "AAPL", "qty": qty, "side": "buy", "type": "market",
                       "order_class": "oto", "time_in_force": "gtc", "stop_loss": {"stop_price": "90"}})


def test_validated_body_is_the_body_posted(broker):
    run, path = broker
    body = payload()
    result = run("order", body)
    assert result.returncode == 0, result.stderr
    assert (path / "posts").read_text().splitlines() == [body]
    assert json.loads(result.stdout)["id"] == "paper-order"
    assert (path / "status").read_text() == "200"


def test_changed_quantity_never_reaches_post(broker):
    run, path = broker
    result = run("order", payload("201"))
    assert result.returncode == 3, result.stderr
    assert "max_position_pct" in result.stderr
    assert not (path / "posts").exists()
    assert (path / "status").read_text() == "000"


def test_naked_buy_never_reaches_post(broker):
    run, path = broker
    result = run("order", json.dumps({"symbol": "AAPL", "qty": "1", "side": "buy",
                                     "type": "market", "time_in_force": "gtc"}))
    assert result.returncode == 3
    assert "OTO" in result.stderr
    assert not (path / "posts").exists()
    assert (path / "status").read_text() == "000"


def test_transport_error_survives_status_capture(broker):
    run, path = broker
    result = run("account", FAKE_TRANSPORT_FAILURE="1")
    assert result.returncode == 7
    assert (path / "status").read_text() == "000"


@pytest.mark.parametrize("status", ["302", "422", "500", "000"])
def test_non_success_status_fails(broker, status):
    run, _ = broker
    assert run("account", FAKE_HTTP_STATUS=status).returncode == 22

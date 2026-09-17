"""Offline regression cases from the September 17 safety audit."""
from decimal import Decimal as D
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from risk_engine import OrderProposal, PortfolioState, validate_order
from scripts.validate_stop_change import validate_trail_path

ROOT = Path(__file__).resolve().parents[1]


def test_tightening_must_not_lower_actual_resting_stop():
    # A high of 130 with a 10% trail leaves a 117 stop. Price has fallen
    # to 120, still 20% above a 100 entry, so the routine requests 5%.
    resting_stop = D("130") * D("0.90")
    replacement_stop = D("120") * D("0.95")
    assert replacement_stop < resting_stop
    result, _, _ = validate_trail_path(
        gain_pct="20", proposed_trail="5", current_trail="10", current_price="120", current_stop="117"
    )
    assert not result.approved, "approved lowering actual stop from 117 to 114"


@pytest.mark.parametrize("protection", [{"stop_price": "1"}, {"trail_percent": "99"}])
def test_entry_protection_must_follow_rule_four(protection):
    state = PortfolioState(equity="100000", cash="100000", is_paper=True)
    order = OrderProposal(symbol="AAPL", qty="1", side="buy", price="100", **protection)
    assert not validate_order(order, state).approved, "approved 99% downside distance"


def test_stocks_only_requires_asset_validation():
    state = PortfolioState(equity="100000", cash="100000", is_paper=True)
    order = OrderProposal(symbol="BTC/USD", qty="1", side="buy", price="100", trail_percent="10")
    assert not validate_order(order, state).approved, "non-equity symbol approved by stocks-only engine"


def run_adapter(tmp_path, curl_source, *, capture_status=False, endpoint=None, command="order"):
    # Copy ONLY the adapter into an isolated tree; stub env loader to ensure
    # the repository's .env and the process's credentials are never read.
    for name in ("scripts", "risk_engine", "ledger"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    adapter = tmp_path / "scripts" / "alpaca.sh"
    (tmp_path / "scripts" / "_env.sh").write_text(":\n")
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/bash\n" + curl_source)
    curl.chmod(0o700)
    env = {
        "PATH": f"{tmp_path}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "ALPACA_API_KEY": "offline-placeholder",
        "ALPACA_SECRET_KEY": "offline-placeholder",
        "ALPACA_RISK_OK": "1",
    }
    if endpoint:
        env["ALPACA_ENDPOINT"] = endpoint
    if capture_status:
        env["ALPACA_HTTP_STATUS_FILE"] = str(tmp_path / "status")
    return subprocess.run(
        ["/bin/bash", str(adapter), command, '{"symbol":"AAPL","qty":"999999","side":"buy","type":"market"}'],
        env=env, capture_output=True, text=True, timeout=5,
    )


def test_mutation_requires_a_real_matching_validation(tmp_path):
    result = run_adapter(tmp_path, "echo offline-broker-called\n")
    assert result.returncode != 0, "flag alone permitted oversized unprotected payload"


def test_transport_failure_must_propagate(tmp_path):
    result = run_adapter(tmp_path, "printf 000\nexit 7\n", capture_status=True, command="account")
    assert result.returncode != 0, "curl connection failure became adapter exit 0"


def test_paper_endpoint_requires_exact_host(tmp_path):
    result = run_adapter(
        tmp_path, "echo offline-broker-called\n",
        endpoint="https://example.invalid/paper-api.alpaca.markets/v2",
    )
    assert result.returncode != 0, "paper hostname substring in path bypassed endpoint guard"

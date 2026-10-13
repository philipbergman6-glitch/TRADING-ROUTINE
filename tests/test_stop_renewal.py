"""Rule 7 (v1.2): renewing an expiring stop at its current level is never a
violation, even when price has drifted within 3% of it (#137). A new
placement or a change still gets rule 7's 3% minimum."""
import json
from pathlib import Path
import subprocess
import sys

from risk_engine import Rule, validate_stop_renewal

CLI = Path(__file__).resolve().parents[1] / "scripts" / "validate_stop_change.py"


def test_same_level_renewal_within_3pct_passes():
    # XLB on Sep 18: stop 2.4% below the close.
    assert validate_stop_renewal(current_stop="48.78", new_stop="48.78", current_price="49.98").approved


def test_renewal_rounded_up_to_the_cent_is_still_a_renewal():
    assert validate_stop_renewal("48.785", "48.79", "49.98").approved


def test_lowered_renewal_is_refused():
    result = validate_stop_renewal(current_stop="48.78", new_stop="48.70", current_price="49.98")
    assert result.broke(Rule.STOP_NEVER_LOWERED)


def test_raise_dressed_as_renewal_is_a_change_and_keeps_the_3pct_minimum():
    result = validate_stop_renewal(current_stop="48.78", new_stop="49.00", current_price="49.98")
    assert result.broke(Rule.STOP_DISTANCE) and not result.broke(Rule.STOP_NEVER_LOWERED)


def test_renewal_at_or_above_price_is_refused():
    assert validate_stop_renewal("50.00", "50.00", "49.98").broke(Rule.STOP_DISTANCE)


def gate(*args):
    proc = subprocess.run([sys.executable, str(CLI), *args, "--json"], capture_output=True, text=True, timeout=15)
    return proc.returncode, json.loads(proc.stdout) if proc.stdout else proc.stderr


def test_cli_renewal_flag_passes_a_same_level_renewal_the_change_gate_refuses():
    price = ("--current-stop", "48.78", "--new-stop", "48.78", "--current-price", "49.98")
    code, out = gate(*price)
    assert code == 3 and [v["rule"] for v in out["violations"]] == ["stop_distance"]
    code, out = gate(*price, "--renewal")
    assert code == 0 and out["approved"] and out["engine_calls"] == ["validate_stop_renewal"]


def test_cli_renewal_flag_still_refuses_a_lowered_level():
    code, out = gate("--current-stop", "48.78", "--new-stop", "48.70", "--current-price", "49.98", "--renewal")
    assert code == 3 and "stop_never_lowered" in [v["rule"] for v in out["violations"]]


def test_cli_renewal_flag_is_price_path_only():
    code, _ = gate("--gain-pct", "16", "--proposed-trail", "7", "--current-stop", "100", "--current-price", "116",
                   "--renewal")
    assert code == 2

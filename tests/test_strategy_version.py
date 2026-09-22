"""STRATEGY_VERSION env must match the declared active version; unset silently meaning v1 is the trap."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("strategy_version", REPO / "scripts" / "strategy_version.py")
sv = importlib.util.module_from_spec(spec)
sys.modules["strategy_version"] = sv
spec.loader.exec_module(sv)

V1_DOC = "# Strategy\n- Instruments: Stocks ONLY\n- Active strategy version: v1 (notes)\n"
V2_DOC = V1_DOC.replace("v1", "v2")


def test_unset_env_matches_v1():
    assert sv.check(V1_DOC, {}) == (0, "STRATEGY_VERSION: v1 (env unset, declared v1)")


def test_unset_env_under_v2_segment_is_a_mismatch():
    code, msg = sv.check(V2_DOC, {})
    assert code == 5 and "MISMATCH" in msg


def test_explicit_match_v2():
    assert sv.check(V2_DOC, {"STRATEGY_VERSION": "v2"})[0] == 0


def test_env_v2_while_declared_v1_is_a_mismatch():
    assert sv.check(V1_DOC, {"STRATEGY_VERSION": "v2"})[0] == 5


def test_unknown_version_raises():
    with pytest.raises(ValueError):
        sv.check(V1_DOC, {"STRATEGY_VERSION": "v9"})


def test_missing_marker_raises():
    with pytest.raises(ValueError):
        sv.check("# Strategy\nno marker\n", {})


def test_repo_strategy_file_declares_a_known_version():
    text = (REPO / "memory" / "TRADING-STRATEGY.md").read_text(encoding="utf-8")
    assert sv.declared_version(text) in {"v1", "v2"}

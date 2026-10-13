"""Every mutation path binds to the approved strategy version (ADR 0011) and
refuses when STRATEGY_VERSION is missing. Tests run as a correctly deployed
runner unless they set or remove the variable themselves."""
import json
from pathlib import Path

import pytest

from scripts.strategy_version import engine_version

_ACTIVE = json.loads((Path(__file__).resolve().parents[1] / "docs" / "rulebook-pins.json").read_text())["active"]


@pytest.fixture(autouse=True)
def deployed_strategy_version(monkeypatch):
    monkeypatch.setenv("STRATEGY_VERSION", engine_version(_ACTIVE))


@pytest.fixture(autouse=True)
def no_real_state_store(monkeypatch):
    """No test may fetch or push the real origin's state/ (ADR 0004). Helpers
    that are not handed a store see an unreachable one and fail closed; tests
    that need a store build a bare origin (tests/store_support.py)."""
    monkeypatch.setenv("TRADING_STATE_REPO", "/nonexistent/trading-routine-state")
    monkeypatch.delenv("TRADING_STATE_STORE", raising=False)
    monkeypatch.delenv("COORDINATOR_FAULT", raising=False)

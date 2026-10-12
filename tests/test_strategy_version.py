"""Version binding (ADR 0011): docs/rulebook-pins.json names the approved version;
the rulebook marker, its hash and STRATEGY_VERSION must all agree with it."""

import json
from pathlib import Path

import pytest

from risk_engine import V1, V2
from scripts import strategy_version as sv
from scripts.strategy_version import VersionBindingError, bind

REPO = Path(__file__).resolve().parent.parent

V11_DOC = "# Strategy\n- Instruments: Stocks ONLY\n- Active strategy version: v1.1 (notes)\n"
V2_DOC = V11_DOC.replace("v1.1", "v2")


def pins(doc=V11_DOC, active="v1.1", **extra):
    return {"active": active, active: {"sha256": sv.rulebook_sha256(doc), **extra}}


def test_consistent_binding_has_no_error_and_selects_the_approved_engine():
    b = bind({"STRATEGY_VERSION": "v1"}, pins=pins(), text=V11_DOC)
    assert (b.approved, b.params, b.error) == ("v1.1", V1, None)
    b.require()


def test_env_may_name_the_full_approved_version():
    assert bind({"STRATEGY_VERSION": "v1.1"}, pins=pins(), text=V11_DOC).error is None


def test_v2_approval_selects_v2_params():
    b = bind({"STRATEGY_VERSION": "v2"}, pins=pins(V2_DOC, "v2"), text=V2_DOC)
    assert b.params is V2 and b.error is None


@pytest.mark.parametrize("environ,expected", [
    ({}, "unset"),                                   # missing: no longer silently v1
    ({"STRATEGY_VERSION": ""}, "unset"),
    ({"STRATEGY_VERSION": "V1"}, "malformed"),
    ({"STRATEGY_VERSION": " v1"}, "malformed"),
    ({"STRATEGY_VERSION": "1"}, "malformed"),
    ({"STRATEGY_VERSION": "v1.x"}, "malformed"),
    ({"STRATEGY_VERSION": "v2"}, "MISMATCH"),
    ({"STRATEGY_VERSION": "v1.2"}, "MISMATCH"),     # a different rulebook revision
    ({"STRATEGY_VERSION": "v9"}, "MISMATCH"),
])
def test_bad_env_is_an_error_but_the_approved_params_survive(environ, expected):
    b = bind(environ, pins=pins(), text=V11_DOC)
    assert expected in b.error and b.approved == "v1.1" and b.params is V1
    with pytest.raises(VersionBindingError, match=expected):
        b.require()


def test_edited_rulebook_without_bump_is_an_error():
    b = bind({"STRATEGY_VERSION": "v1"}, pins=pins(), text=V11_DOC + "15. A rule slipped in\n")
    assert "RULEBOOK CHANGED" in b.error and b.params is V1


def test_marker_disagreeing_with_the_approved_version_is_an_error():
    b = bind({"STRATEGY_VERSION": "v1"}, pins=pins(V11_DOC, "v1.1"), text=V2_DOC)
    assert "declares v2" in b.error and b.params is V1


def test_missing_marker_is_an_error():
    doc = "# Strategy\nno marker\n"
    assert "marker" in bind({"STRATEGY_VERSION": "v1"}, pins=pins(doc), text=doc).error


def test_unreadable_rulebook_is_an_error_not_a_crash(tmp_path):
    b = bind({"STRATEGY_VERSION": "v1"}, pins=pins(), rulebook=tmp_path / "missing.md")
    assert "rulebook unreadable" in b.error and b.params is V1


@pytest.mark.parametrize("bad,reason", [
    ({"v1.1": {"sha256": "ab" * 32}}, "active"),
    ({"active": "v1.1"}, "no pin"),
    ({"active": "v1.1", "v1.1": {"sha256": "short"}}, "sha256"),
    ({"active": "v1.1 ", "v1.1 ": {"sha256": "ab" * 32}}, "active"),
    ({"active": "v7", "v7": {"sha256": "ab" * 32}}, "unknown"),
    ({"active": "v1", "v1": {"sha256": "ab" * 32, "until": "2026-09-24"}}, "closed"),
    ([], "object"),
])
def test_pins_that_cannot_name_an_approved_version_raise(bad, reason):
    with pytest.raises(VersionBindingError, match=reason):
        bind({"STRATEGY_VERSION": "v1"}, pins=bad, text=V11_DOC)


def test_unreadable_pins_file_raises(tmp_path):
    with pytest.raises(VersionBindingError, match="pins"):
        bind({"STRATEGY_VERSION": "v1"}, pins_file=tmp_path / "missing.json", text=V11_DOC)


def test_repo_pins_approve_the_committed_rulebook():
    b = bind({"STRATEGY_VERSION": sv.engine_version(json.loads((REPO / "docs/rulebook-pins.json").read_text())["active"])})
    assert b.error is None


@pytest.mark.parametrize("environ,code", [({"STRATEGY_VERSION": "v1"}, 0), ({}, 5), ({"STRATEGY_VERSION": "v2"}, 5)])
def test_cli_exit_codes(monkeypatch, capsys, environ, code):
    monkeypatch.delenv("STRATEGY_VERSION", raising=False)
    for k, v in environ.items():
        monkeypatch.setenv(k, v)
    assert sv.main() == code
    out = capsys.readouterr()
    assert ("STRATEGY_VERSION: v1 " in out.out) if code == 0 else ("STRATEGY_VERSION" in out.err)

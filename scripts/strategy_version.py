#!/usr/bin/env python3
"""Bind a run to the approved strategy version, or say exactly why it cannot be bound.

One source names the approved version: the "active" key of
docs/rulebook-pins.json (ADR 0011). Three things must agree with it:

1. memory/TRADING-STRATEGY.md declares it ("- Active strategy version: vN[.M]").
2. The rulebook's sha256 equals the pin recorded for it. Any edit to the
   rulebook without a version bump and a new pin is refused (spec section 5:
   a segment is never re-scored under a later rule set; 2026-09-25 rule 14
   slipped in unpinned).
3. STRATEGY_VERSION names it: the engine part ("v1") or the full version
   ("v1.1"). Unset is refused, not read as v1: a runner that lost the variable
   is a deployment fault, and only the major part selects engine parameters.

`bind()` is called by every mutation path (submit_entry, close_position,
replace_stop, validate_mutation, protection_monitor). A failed check still
yields the approved version's parameters, because protective-stop restoration
on an unprotected position proceeds under them (ADR 0011 names the exact
operations); everything else refuses. Pins that cannot name an approved
version raise VersionBindingError: nothing can proceed.

    python3 scripts/strategy_version.py   # routine gate

Exit codes: 0 bound · 1 pins file unreadable or invalid · 5 env, marker or hash disagrees.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from risk_engine.versions import STRATEGY_VERSION_ENV, VERSIONS, StrategyParams  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STRATEGY_FILE = ROOT / "memory" / "TRADING-STRATEGY.md"
PINS_FILE = ROOT / "docs" / "rulebook-pins.json"
MARKER = re.compile(r"^- Active strategy version:\s*(v\d+(?:\.\d+)?)\b", re.MULTILINE)
VERSION = re.compile(r"v\d+(?:\.\d+)?")
SHA256 = re.compile(r"[0-9a-f]{64}")


class VersionBindingError(ValueError):
    """The run is not bound to the approved strategy version."""


@dataclass(frozen=True)
class Binding:
    approved: str            # pins "active", e.g. "v1.1"
    params: StrategyParams   # the approved version's engine parameters
    error: str | None        # None when env, marker and hash all agree

    def require(self) -> None:
        if self.error:
            raise VersionBindingError(self.error)

    def as_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "engine": self.params.name, "error": self.error}


def declared_version(text: str) -> str:
    found = MARKER.findall(text)
    if len(found) != 1:
        raise ValueError(f"expected exactly one 'Active strategy version' marker, found {len(found)}")
    return found[0].lower()


def engine_version(version: str) -> str:
    """v1.1 -> v1: the minor part is a rulebook revision, not new engine params."""
    return version.split(".", 1)[0]


def rulebook_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def approved_version(pins: object) -> tuple[str, str]:
    """(approved version, its pinned sha256) from the pins mapping; raises when it names none."""
    if not isinstance(pins, Mapping):
        raise VersionBindingError("rulebook pins must be a JSON object")
    active = pins.get("active")
    if not isinstance(active, str) or not VERSION.fullmatch(active):
        raise VersionBindingError(f"rulebook pins 'active' must name a version like v1.1, got {active!r}")
    pin = pins.get(active)
    if not isinstance(pin, Mapping):
        raise VersionBindingError(f"no pin for approved version {active} in {PINS_FILE.name}")
    if not isinstance(pin.get("sha256"), str) or not SHA256.fullmatch(pin["sha256"]):
        raise VersionBindingError(f"pin for {active} has no valid sha256")
    if "until" in pin:
        raise VersionBindingError(f"approved version {active} is closed (until {pin['until']})")
    if engine_version(active) not in VERSIONS:
        raise VersionBindingError(f"approved version {active} has unknown engine; known: {sorted(VERSIONS)}")
    return active, pin["sha256"]


def _env_error(raw: str | None, approved: str) -> str | None:
    engine = engine_version(approved)
    if raw is None or raw == "":
        return f"STRATEGY_VERSION is unset; the approved version is {approved}: set STRATEGY_VERSION={engine}"
    if raw in (engine, approved):
        return None
    if not VERSION.fullmatch(raw):
        return f"STRATEGY_VERSION {raw!r} is malformed; expected {engine} (approved {approved})"
    return f"STRATEGY_VERSION MISMATCH: env {raw}, approved {approved} (set STRATEGY_VERSION={engine})"


def _rulebook_error(text: str, approved: str, sha: str) -> str | None:
    try:
        declared = declared_version(text)
    except ValueError as exc:
        return f"rulebook {exc}"
    if declared != approved:
        return f"rulebook declares {declared}, pins approve {approved}"
    got = rulebook_sha256(text)
    if got != sha:
        return (f"RULEBOOK CHANGED without version bump: approved {approved} pinned {sha[:12]}, file is "
                f"{got[:12]}. Bump the version and pin it ({PINS_FILE.name}) or revert {STRATEGY_FILE.name}")
    return None


def bind(environ: Mapping[str, str] | None = None, *, pins: object = None, text: str | None = None,
         pins_file: Path | None = None, rulebook: Path | None = None) -> Binding:
    """The approved version and whether this run is bound to it. Raises only when no
    version is approved; every other disagreement is returned in `error`."""
    environ = os.environ if environ is None else environ
    pins_file, rulebook = pins_file or PINS_FILE, rulebook or STRATEGY_FILE
    if pins is None:
        try:
            pins = json.loads(pins_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VersionBindingError(f"rulebook pins unreadable: {exc}") from exc
    approved, sha = approved_version(pins)
    params = VERSIONS[engine_version(approved)]
    error = _env_error(environ.get(STRATEGY_VERSION_ENV), approved)
    if error is None:
        if text is None:
            try:
                text = rulebook.read_text(encoding="utf-8")
            except OSError as exc:
                error = f"rulebook unreadable: {exc}"
        if text is not None:
            error = _rulebook_error(text, approved, sha)
    return Binding(approved, params, error)


def main() -> int:
    try:
        binding = bind()
    except VersionBindingError as exc:
        print(f"strategy version check failed: {exc}", file=sys.stderr)
        return 1
    if binding.error:
        print(binding.error, file=sys.stderr)
        return 5
    print(f"STRATEGY_VERSION: {binding.params.name} (env {os.environ[STRATEGY_VERSION_ENV]}, "
          f"approved {binding.approved}, rulebook pinned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Hard-fail when the active strategy version is inconsistent with env or rulebook.

Two checks, both against memory/TRADING-STRATEGY.md:

1. The "Active strategy version: vN[.M]" marker must agree with the
   STRATEGY_VERSION env var. Unset env means v1 by design
   (risk_engine.versions), so a v2 segment whose runner lost the variable
   would otherwise trade v1 rules silently. Only the major part (vN) selects
   engine parameters; a minor part (vN.M) is a rulebook revision under the
   same engine.

2. The sha256 of the rulebook must equal the pin recorded for the declared
   version in docs/rulebook-pins.json. Any edit to the rulebook without a
   version bump and a new pin is refused (spec section 5: a segment is never
   re-scored under a later rule set; 2026-09-25 rule 14 slipped in unpinned).

Exit codes: 0 match · 1 file/marker/env/pin unreadable · 5 mismatch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from risk_engine.versions import STRATEGY_VERSION_ENV, params_from_env  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STRATEGY_FILE = ROOT / "memory" / "TRADING-STRATEGY.md"
PINS_FILE = ROOT / "docs" / "rulebook-pins.json"
MARKER = re.compile(r"^- Active strategy version:\s*(v\d+(?:\.\d+)?)\b", re.MULTILINE)


def declared_version(text: str) -> str:
    found = MARKER.findall(text)
    if len(found) != 1:
        raise ValueError(f"expected exactly one 'Active strategy version' marker, found {len(found)}")
    return found[0].lower()


def engine_version(declared: str) -> str:
    """v1.1 -> v1: the minor part is a rulebook revision, not new engine params."""
    return declared.split(".", 1)[0]


def rulebook_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check(text: str, environ: Mapping[str, str], pins: Mapping[str, Mapping[str, str]] | None = None) -> tuple[int, str]:
    declared = declared_version(text)
    expected = engine_version(declared)
    active = params_from_env(environ).name
    raw = environ.get(STRATEGY_VERSION_ENV)
    shown = raw if raw else "unset"
    if active != expected:
        return 5, f"STRATEGY_VERSION MISMATCH: env {shown} -> {active}, declared {declared}"
    if pins is not None:
        pin = pins.get(declared)
        if pin is None or "sha256" not in pin:
            raise ValueError(f"no rulebook pin for declared version {declared} in {PINS_FILE.name}")
        got = rulebook_sha256(text)
        if got != pin["sha256"]:
            return 5, (f"RULEBOOK CHANGED without version bump: declared {declared} pinned "
                       f"{pin['sha256'][:12]}, file is {got[:12]}. Bump the version and pin it "
                       f"(docs/rulebook-pins.json) or revert memory/TRADING-STRATEGY.md")
    pinned = ", rulebook pinned" if pins is not None else ""
    return 0, f"STRATEGY_VERSION: {active} (env {shown}, declared {declared}{pinned})"


def main() -> int:
    try:
        pins = json.loads(PINS_FILE.read_text(encoding="utf-8"))
        code, msg = check(STRATEGY_FILE.read_text(encoding="utf-8"), os.environ, pins)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"strategy version check failed: {exc}", file=sys.stderr)
        return 1
    print(msg, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())

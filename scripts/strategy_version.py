#!/usr/bin/env python3
"""Hard-fail when the STRATEGY_VERSION env var disagrees with the declared active version.

Source of truth: the "Active strategy version: vN" line in memory/TRADING-STRATEGY.md.
Unset env means v1 by design (risk_engine.versions), so a v2 segment whose runner
lost the variable would otherwise trade v1 rules silently. Exit codes:
  0 match · 1 file/marker/env unreadable · 5 mismatch.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from risk_engine.versions import STRATEGY_VERSION_ENV, params_from_env  # noqa: E402

STRATEGY_FILE = Path(__file__).resolve().parent.parent / "memory" / "TRADING-STRATEGY.md"
MARKER = re.compile(r"^- Active strategy version:\s*(v\d+)\b", re.MULTILINE)


def declared_version(text: str) -> str:
    found = MARKER.findall(text)
    if len(found) != 1:
        raise ValueError(f"expected exactly one 'Active strategy version' marker, found {len(found)}")
    return found[0].lower()


def check(text: str, environ) -> tuple[int, str]:
    expected = declared_version(text)
    active = params_from_env(environ).name
    raw = environ.get(STRATEGY_VERSION_ENV)
    shown = raw if raw else "unset"
    if active != expected:
        return 5, f"STRATEGY_VERSION MISMATCH: env {shown} -> {active}, declared {expected}"
    return 0, f"STRATEGY_VERSION: {active} (env {shown}, declared {expected})"


def main() -> int:
    try:
        code, msg = check(STRATEGY_FILE.read_text(encoding="utf-8"), os.environ)
    except (OSError, ValueError) as exc:
        print(f"strategy version check failed: {exc}", file=sys.stderr)
        return 1
    print(msg, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())

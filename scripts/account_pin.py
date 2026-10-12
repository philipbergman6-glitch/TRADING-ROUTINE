#!/usr/bin/env python3
"""Pinned broker account per profile: the only in-band check between two paper accounts.

Alpaca serves every paper account from the same host and no payload says which
account answered (research 0010); only `account_number` does. scripts/accounts.json
pins the expected number per profile, and alpaca.sh compares it against
`GET /v2/account` before any write.

    python3 scripts/account_pin.py check <profile> < account.json   # prints the number; exit 8 on mismatch
    python3 scripts/account_pin.py set <profile> <account_number> <id> [--file PATH]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
PINS_FILE = ROOT / "scripts" / "accounts.json"
PROFILES = ("production", "drill")
EXIT_PIN = 8
_NUMBER = re.compile(r"^[A-Z0-9]{6,32}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _read(path: Path) -> dict:
    try:
        pins = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read account pins at {path}: {exc}") from exc
    if not isinstance(pins, dict) or set(pins) != set(PROFILES):
        raise ValueError(f"{path} must contain exactly the profiles {PROFILES}")
    return pins


def load_pin(profile: str, path: Path = PINS_FILE) -> str | None:
    """Pinned account_number for `profile`, or None when the profile is not pinned yet."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    entry = _read(path)[profile]
    if not isinstance(entry, dict) or "account_number" not in entry:
        raise ValueError(f"profile {profile!r} entry must be an object with account_number")
    number = entry["account_number"]
    if number is None:
        return None
    if not isinstance(number, str) or not _NUMBER.match(number):
        raise ValueError(f"profile {profile!r} has a malformed account_number pin")
    return number


def check_pin(pinned: str | None, payload: dict) -> str:
    """Return the broker's account_number when it equals the pin; raise otherwise."""
    if pinned is None:
        raise ValueError("profile is not pinned; run scripts/account_pin.py set first")
    number = payload.get("account_number") if isinstance(payload, dict) else None
    if not isinstance(number, str) or not number:
        raise ValueError("broker account payload has no account_number")
    if number != pinned:
        raise ValueError(f"broker answered as account {number}, pinned {pinned}")
    return number


def set_pin(profile: str, number: str, account_id: str, path: Path = PINS_FILE) -> None:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    if not _NUMBER.match(number):
        raise ValueError("account_number must be 6-32 uppercase alphanumerics")
    if not _UUID.match(account_id):
        raise ValueError("id must be a lowercase UUID")
    pins = _read(path)
    pins[profile] = {"account_number": number, "id": account_id}
    path.write_text(json.dumps(pins, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=PINS_FILE)
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="compare the account JSON on stdin with the pin")
    chk.add_argument("profile")
    st = sub.add_parser("set", help="record a profile's account_number and id")
    st.add_argument("profile")
    st.add_argument("account_number")
    st.add_argument("id")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            payload = json.loads(sys.stdin.read())
            print(check_pin(load_pin(args.profile, args.file), payload))
            return 0
        set_pin(args.profile, args.account_number, args.id, args.file)
        print(f"pinned {args.profile} -> {args.account_number}")
        return 0
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"account_pin: REFUSING ({args.cmd} {args.profile}): {exc}", file=sys.stderr)
        return EXIT_PIN


if __name__ == "__main__":
    sys.exit(main())

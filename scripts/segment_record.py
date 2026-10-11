#!/usr/bin/env python3
"""Predeclared experiment segment records (docs/STRATEGY-SPEC.md section 5).

    python3 scripts/segment_record.py --open 0001 --start 2026-10-13 [--write]
    python3 scripts/segment_record.py --check

A segment is the unit that gets scored. Opening one freezes what the score
depends on: the declared rulebook version and its sha256, the sha256 of every
routine and command prompt, the code commit, and the model ids the routines
have been committing under. The record is a JSON file under docs/experiments/,
written once and never edited by a routine.

`--check` recomputes the rulebook and prompt hashes for every segment whose
status is "open" and exits 5 if any differ from the working tree. A rulebook or
prompt edit during an open segment therefore fails CI until the segment is
closed (status "closed", end_date set) and a new one opened. That is the
discipline the spec asks for: a segment is never re-scored under a later rule
set.

Nothing here reads the broker. The baseline equity is filled in by hand from
the broker's close on the start date, and the record says so.

Exit codes: 0 ok · 1 unreadable input · 5 an open segment no longer matches the tree.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.strategy_version import declared_version, engine_version, rulebook_sha256  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "docs" / "experiments"
STRATEGY_FILE = ROOT / "memory" / "TRADING-STRATEGY.md"
PROMPT_GLOBS = ("routines/*.md", ".claude/commands/*.md")
EXIT_OK, EXIT_UNREADABLE, EXIT_DRIFT = 0, 1, 5

# Commit subject prefix each routine pushes (routines/*.md STEP 7/8); the
# Co-Authored-By trailer on those commits names the model that ran it.
ROUTINE_PREFIXES = {
    "pre-market": ("pre-market research",),
    "market-open": ("market-open trades", "market-open held"),
    "midday": ("midday scan",),
    "daily-summary": ("EOD snapshot",),
    "weekly-review": ("weekly review",),
}
TRAILER_SEP = "\x1f"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_hashes(root: Path = ROOT, globs: Iterable[str] = PROMPT_GLOBS) -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path.name == "README.md":
                continue
            out[path.relative_to(root).as_posix()] = sha256_text(path.read_text(encoding="utf-8"))
    if not out:
        raise ValueError("no prompt files found")
    return out


def model_ids_from_log(lines: Iterable[str], prefixes: Mapping[str, tuple[str, ...]] = ROUTINE_PREFIXES) -> dict[str, list[str]]:
    """Map routine -> sorted model names seen in Co-Authored-By trailers.

    Each line is "<subject>\\x1f<trailer values, newline separated>". A routine
    whose commits carry no trailer maps to [] so the gap is visible.
    """
    seen: dict[str, set[str]] = {name: set() for name in prefixes}
    for line in lines:
        subject, _, trailers = line.partition(TRAILER_SEP)
        for name, subject_prefixes in prefixes.items():
            if subject.startswith(subject_prefixes):
                for value in trailers.split("\n"):
                    value = value.strip()
                    if value:
                        seen[name].add(re.sub(r"\s*<[^>]*>\s*$", "", value))
    return {name: sorted(models) for name, models in seen.items()}


def git_log_lines(root: Path = ROOT, limit: int = 200) -> list[str]:
    fmt = f"%s{TRAILER_SEP}%(trailers:key=Co-Authored-By,valueonly)"
    out = subprocess.run(["git", "log", f"-{limit}", f"--format={fmt}", "HEAD"],
                         cwd=root, capture_output=True, text=True, check=True).stdout
    # Trailer values may span lines; split records on the subject line of the next commit
    records, current = [], None
    for raw in out.splitlines():
        if TRAILER_SEP in raw:
            if current is not None:
                records.append(current)
            current = raw
        elif current is not None and raw.strip():
            current += "\n" + raw
    if current is not None:
        records.append(current)
    return records


def git_head(root: Path = ROOT) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()


def build_record(*, segment_id: str, start: date, rulebook_text: str, prompts: Mapping[str, str],
                 code_commit: str, model_ids: Mapping[str, list[str]], opened_on: date) -> dict:
    declared = declared_version(rulebook_text)
    return {
        "segment_id": segment_id,
        "status": "open",
        "opened_on": str(opened_on),
        "start_date": str(start),
        "end_date": None,
        "strategy_version": declared,
        "engine_version": engine_version(declared),
        "code_commit": code_commit,
        "rulebook": {"path": "memory/TRADING-STRATEGY.md", "sha256": rulebook_sha256(rulebook_text)},
        "prompts": dict(prompts),
        "model_ids": {k: list(v) for k, v in model_ids.items()},
        "model_id_source": "Co-Authored-By trailer on each routine's commits; cloud routine configuration not inspected",
        "account": {
            "environment": "paper",
            "starting_capital_usd": 100000,
            "baseline_equity_usd": None,
            "baseline_rule": "Alpaca last_equity at the close before start_date; fill in by hand, never from the markdown log",
            "test_orders_present": True,
            "test_orders_note": "Seven 1-3 share F fills on 2026-08-11 (ADR 0002 engineering tests) remain in this account and are excluded from statistics; see docs/research/0006",
        },
        "universe": "US common equities and SPDR Select Sector ETFs, stocks only, no options, no margin (rulebook rules 1 and 13)",
        "benchmarks": {
            "primary": "SPY, Alpaca IEX daily close, adjustment=all, identical dates",
            "secondary": "SPY scaled by the bot's daily invested fraction (exposure-matched)",
            "mechanical": "sector-momentum policy as specified in docs/PAPER-EXPERIMENT.md, to be fully specified before scoring",
        },
        "scoring": {
            "return": "broker daily closes only; markdown EOD snapshots are narrative",
            "costs": "paper fees as charged; model, research and hosting spend logged monthly (spec section 5 item 5, not yet started)",
            "review_threshold": "owner decision pending (spec section 7 item 1); recommended peak-to-trough $1,000 at $10,000 scale",
            "funding_criterion": "docs/STRATEGY-ASSESSMENT.md section 5 item 5, stated 2026-09-19, applies unchanged",
        },
        "invariants": [
            "rulebook sha256 and every prompt sha256 above must match the tree while status is open (scripts/segment_record.py --check)",
            "STRATEGY_VERSION in every runner must match engine_version (scripts/strategy_version.py)",
            "no order outside scripts/alpaca.sh; no bulk mutation; paper endpoint only",
        ],
    }


def check_open_segments(records: Iterable[tuple[str, dict]], rulebook_text: str,
                        prompts: Mapping[str, str]) -> list[str]:
    """Pure: name every way an open segment disagrees with the current tree."""
    problems: list[str] = []
    current_sha = rulebook_sha256(rulebook_text)
    for name, rec in records:
        if rec.get("status") != "open":
            continue
        if rec.get("rulebook", {}).get("sha256") != current_sha:
            problems.append(f"{name}: rulebook sha256 changed during open segment")
        recorded = rec.get("prompts", {})
        for path, sha in recorded.items():
            if prompts.get(path) != sha:
                problems.append(f"{name}: prompt changed or removed during open segment: {path}")
        for path in prompts:
            if path not in recorded:
                problems.append(f"{name}: new prompt not covered by the segment record: {path}")
        try:
            if declared_version(rulebook_text) != rec.get("strategy_version"):
                problems.append(f"{name}: declared rulebook version differs from the segment's")
        except ValueError as exc:
            problems.append(f"{name}: {exc}")
    return problems


def load_records(folder: Path = EXPERIMENTS) -> list[tuple[str, dict]]:
    return [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(folder.glob("*.json"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--open", metavar="ID", help="build a new open segment record with this id, e.g. 0001")
    parser.add_argument("--start", help="YYYY-MM-DD first scored session (required with --open)")
    parser.add_argument("--write", action="store_true", help="write docs/experiments/<id>-<version>-segment.json")
    parser.add_argument("--check", action="store_true", help="verify every open segment still matches the tree")
    args = parser.parse_args()
    try:
        rulebook = STRATEGY_FILE.read_text(encoding="utf-8")
        prompts = prompt_hashes()
        if args.check:
            problems = check_open_segments(load_records(), rulebook, prompts)
            print(json.dumps({"open_segments_ok": not problems, "problems": problems}, indent=2))
            return EXIT_DRIFT if problems else EXIT_OK
        if args.open:
            if not args.start:
                parser.error("--open requires --start")
            rec = build_record(segment_id=args.open, start=date.fromisoformat(args.start), rulebook_text=rulebook,
                               prompts=prompts, code_commit=git_head(), model_ids=model_ids_from_log(git_log_lines()),
                               opened_on=date.today())
            text = json.dumps(rec, indent=2, ensure_ascii=False) + "\n"
            if args.write:
                EXPERIMENTS.mkdir(parents=True, exist_ok=True)
                target = EXPERIMENTS / f"{args.open}-{rec['strategy_version']}-segment.json"
                if target.exists():
                    raise ValueError(f"{target.relative_to(ROOT)} exists; records are written once")
                target.write_text(text, encoding="utf-8")
                print(str(target.relative_to(ROOT)))
            else:
                print(text, end="")
            return EXIT_OK
        parser.error("choose --open or --check")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"segment record failed: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

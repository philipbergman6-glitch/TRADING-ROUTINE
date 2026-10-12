"""Every rule in the rulebook has an owner in the v1 enforcement table (#107).

The table in docs/STRATEGY-SPEC.md section 2.1 is the contract for who
enforces what. A rule added to memory/TRADING-STRATEGY.md without a row is a
standing intention with no mechanism, which is how rule 14 entered unowned.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

REPO = Path(__file__).resolve().parent.parent
RULEBOOK = REPO / "memory" / "TRADING-STRATEGY.md"
SPEC = REPO / "docs" / "STRATEGY-SPEC.md"
CLASSES = ("Engine", "Script", "Monitor", "Advisory")


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def rulebook_rules(text: str) -> set[int]:
    core = _section(text, "## Core Rules", "\n## ")
    return {int(n) for n in re.findall(r"^(\d+)\. ", core, re.MULTILINE)}


def table_rows(text: str) -> dict[str, list[str]]:
    """Section 2.1 rows keyed by the # cell ("1".."14", "checklist")."""
    table = _section(text, "### 2.1 ", "\n### ")
    rows: dict[str, list[str]] = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or cells[0] in ("#", "") or set(cells[0]) <= {"-"}:
            continue
        if cells[0] in rows:
            raise AssertionError(f"duplicate row {cells[0]}")
        rows[cells[0]] = cells
    return rows


def test_every_rulebook_rule_has_a_row() -> None:
    rules = rulebook_rules(RULEBOOK.read_text())
    rows = table_rows(SPEC.read_text())
    assert rules, "no numbered rules found under ## Core Rules"
    assert {str(n) for n in rules} | {"checklist"} == set(rows)


@pytest.mark.parametrize("key,cells", sorted(table_rows(SPEC.read_text()).items()))
def test_each_row_names_a_class_and_an_enforcing_file(key: str, cells: list[str]) -> None:
    _, _, owner_class, enforced_by, *_ = cells
    assert any(c in owner_class for c in CLASSES), f"row {key}: no enforcement class in {owner_class!r}"
    paths = re.findall(r"`([\w./-]+\.(?:py|md|json|yml))", enforced_by)
    assert paths, f"row {key}: names no enforcing file"
    for path in paths:
        assert (REPO / path).exists(), f"row {key}: {path} does not exist"


def test_a_rule_without_a_row_is_caught() -> None:
    text = RULEBOOK.read_text().replace("## Entry Checklist", "15. A new rule\n\n## Entry Checklist")
    assert rulebook_rules(text) - {int(k) for k in table_rows(SPEC.read_text()) if k.isdigit()} == {15}


BUY_PATHS = (
    REPO / "routines" / "market-open.md",
    REPO / ".claude" / "commands" / "market-open.md",
    REPO / ".claude" / "commands" / "trade.md",
)


@pytest.mark.parametrize("path", BUY_PATHS, ids=lambda p: str(p.relative_to(REPO)))
def test_buy_paths_check_rules_10_and_14_before_validating(path: Path) -> None:
    text = path.read_text()
    validate = text.index("validate_order.py --symbol SYM --qty N --side buy")
    assert text.index("blotter.py --sector-streaks") < validate, "rule 10 is Script: computed before the buy"
    assert text.index("Composition waiver") < validate, "rule 14: a broad ETF needs a recorded waiver"


@pytest.mark.parametrize(
    "path",
    (REPO / "routines" / "pre-market.md", REPO / ".claude" / "commands" / "pre-market.md"),
    ids=lambda p: str(p.relative_to(REPO)),
)
def test_mandate_fallback_is_constrained_by_rule_14(path: Path) -> None:
    mandate = _section(path.read_text(), "Exit 5 → MANDATE DUE", "\nSTEP 3")
    assert "single name" in mandate and "Composition waiver" in mandate
    assert "never a reason to defer or skip the add" in mandate

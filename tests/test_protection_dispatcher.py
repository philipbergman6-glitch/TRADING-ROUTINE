"""The external protection dispatcher (ADR 0009) stays in step with the workflow
it dispatches. The worker's behaviour is tested in dispatcher/worker.test.js
(node --test, run by tests.yml); these guard the configuration seams."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRANGLER = ROOT / "dispatcher" / "wrangler.toml"
WORKFLOWS = ROOT / ".github" / "workflows"
MONITOR_YML = WORKFLOWS / "protection-monitor.yml"

DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _expand(field: str, names: dict[str, int] | None = None) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        bounds = [names[b.upper()] if names and b.upper() in names else int(b)
                  for b in part.split("-")]
        if len(bounds) == 1:
            values.add(bounds[0])
        else:
            values.update(range(bounds[0], bounds[1] + 1))
    return values


def slots(cron: str, dialect: str) -> set[tuple[str, int, int]]:
    """(weekday, hour, minute) UTC slots of a five-field cron with plain
    lists/ranges. GitHub numbers weekdays 0=Sunday; Cloudflare 1=Sunday and
    also accepts names."""
    minute, hour, dom, month, dow = cron.split()
    assert (dom, month) == ("*", "*"), cron
    if dialect == "github":
        days = {DAYS[d] for d in _expand(dow)}
    else:
        days = {DAYS[d - 1] for d in _expand(dow, {n: i + 1 for i, n in enumerate(DAYS)})}
    return {(d, h, m) for d in days for h in _expand(hour) for m in _expand(minute)}


def wrangler() -> dict:
    return tomllib.loads(WRANGLER.read_text())


def monitor_yml() -> str:
    return MONITOR_YML.read_text()


def test_dispatcher_fires_every_30_minutes_through_the_session_on_weekdays():
    (cron,) = wrangler()["triggers"]["crons"]
    expected = {(d, h, m) for d in ["MON", "TUE", "WED", "THU", "FRI"]
                for h in range(13, 21) for m in (0, 30)}
    # 13:00-20:30Z covers 09:30-16:00 ET in both EDT and EST.
    assert slots(cron, "cloudflare") == expected


def test_dispatcher_slots_match_the_workflow_schedule():
    (gh_cron,) = re.findall(r'-\s*cron:\s*"([^"]+)"', monitor_yml())
    (cf_cron,) = wrangler()["triggers"]["crons"]
    assert slots(cf_cron, "cloudflare") == slots(gh_cron, "github")


def test_dispatcher_targets_the_protection_monitor_on_main():
    vars_ = wrangler()["vars"]
    assert vars_["WORKFLOW_FILE"] == MONITOR_YML.name
    assert vars_["WORKFLOW_REF"] == "main"
    assert re.fullmatch(r"[\w-]+/[\w.-]+", vars_["GITHUB_REPOSITORY"])


def test_the_token_is_a_worker_secret_never_a_committed_var():
    text = WRANGLER.read_text()
    assert "GH_DISPATCH_TOKEN" not in wrangler().get("vars", {})
    assert not re.search(r"(github_pat_|ghp_)\w+", text)


def test_workflow_keeps_concurrency_and_the_manual_dry_run_default():
    yml = monitor_yml()
    assert re.search(r"concurrency:\s*\n\s+group: protection-monitor\s*\n\s+cancel-in-progress: false", yml)
    assert re.search(r"dry_run:\s*\n(\s+\w+:.*\n)*?\s+type: boolean\s*\n\s+default: true", yml)
    # A dispatch with dry_run=true plans only; the dispatcher sends "false".
    assert re.search(r'"\$\{\{ inputs.dry_run \}\}" = "true" \]; then\s*\n\s+python3 scripts/protection_monitor.py --dry-run', yml)


def test_ci_runs_the_worker_tests():
    assert "node --test dispatcher/worker.test.js" in (WORKFLOWS / "tests.yml").read_text()

"""scripts/alert_unverified.sh: a send-only Resend key is raised once a day as a
GitHub issue and one workflow warning, never as a failed job (ticket #147)."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "alert_unverified.sh"
WORKFLOWS = ROOT / ".github" / "workflows"

# A stub gh: records every call; `issue list` answers with $STUB_EXISTING.
GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_LOG"
if [[ "$1 $2" == "issue list" ]]; then printf '%s' "${STUB_EXISTING:-}"; fi
"""


def run(tmp_path, marker_text=None, existing=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "gh").write_text(GH)
    (bin_dir / "gh").chmod(0o755)
    marker = tmp_path / "email-unverified"
    if marker_text is not None:
        marker.write_text(marker_text)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_LOG": str(tmp_path / "gh.log"),
           "STUB_EXISTING": existing, "GITHUB_REPOSITORY": "o/r"}
    r = subprocess.run(["bash", str(SCRIPT), str(marker)], env=env, capture_output=True, text=True, timeout=30)
    log = (tmp_path / "gh.log").read_text() if (tmp_path / "gh.log").exists() else ""
    return r, log


def test_no_unverified_email_means_no_alert(tmp_path):
    r, log = run(tmp_path)
    assert r.returncode == 0 and log == "" and "::warning" not in r.stdout


def test_first_unverified_email_of_the_day_opens_one_issue_and_one_warning(tmp_path):
    r, log = run(tmp_path, "2026-10-13T22:50:00Z id=e1 restricted_api_key\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("::warning") == 1 and "delivery unverifiable: restricted key" in r.stdout
    assert log.count("issue create") == 1
    create = log[log.index("issue create"):]
    assert "ALERT DELIVERY UNVERIFIED" in create and "RESEND_API_KEY" in create and "id=e1" in create


def test_already_alerted_today_does_not_open_another(tmp_path):
    r, log = run(tmp_path, "t id=e2 restricted_api_key\n", existing="141")
    assert r.returncode == 0 and r.stdout.count("::warning") == 1
    assert "--state all" in log and not any(line.startswith("issue create") for line in log.splitlines())


def test_both_alerting_workflows_raise_it():
    for name in ("heartbeat.yml", "protection-monitor.yml"):
        text = (WORKFLOWS / name).read_text()
        assert "EMAIL_UNVERIFIED_FILE" in text and "scripts/alert_unverified.sh" in text, name
        assert "issues: write" in text, name

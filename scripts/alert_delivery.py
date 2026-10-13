"""Send an alert through scripts/email.sh and say how far its delivery is known.

    verified    Resend accepted it and its status shows no bounce or failure
    unverified  Resend accepted it, but the status was not read: the key is
                send-only (email.sh exit 0, `delivery=unverified`), a named
                configuration failure, not a lost alert (ticket #147)
    failed      not sent, bounced, or the status read failed otherwise

Only "failed" means the owner was not told; callers fail their job on it
(ADR 0007). email.sh's output goes to stderr so a caller's stdout stays its
JSON report.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

EMAIL = Path(__file__).resolve().parent / "email.sh"
VERIFIED, UNVERIFIED, FAILED = "verified", "unverified", "failed"


def send(body: str, run=subprocess.run) -> str:
    try:
        done = run(["bash", str(EMAIL), body], check=False, timeout=120, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return FAILED
    for stream in (done.stdout, done.stderr):
        if stream:
            sys.stderr.write(stream)
    if done.returncode != 0:
        return FAILED
    # Exit 0 without the verified verdict proves only that Resend accepted it.
    verdicts = [line.split()[0] for line in (done.stdout or "").splitlines() if line.startswith("delivery=")]
    return VERIFIED if verdicts and verdicts[-1] == "delivery=verified" else UNVERIFIED

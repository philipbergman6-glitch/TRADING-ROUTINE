"""scripts/email.sh is delivery-verified: it captures the Resend id, reads the
email's last_event back, and exits non-zero whenever it cannot prove the
alert was accepted (ADR 0007). Exercised end to end against a stub Resend."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

ROOT = Path(__file__).resolve().parent.parent
EMAIL = ROOT / "scripts" / "email.sh"


class Stub:
    """Scripted Resend: `post` is (status, body); `gets` is a queue of (status, body)."""

    def __init__(self, post, gets):
        self.post, self.gets, self.requests = post, list(gets), []
        stub = self

        class H(BaseHTTPRequestHandler):
            def _reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                stub.requests.append(("POST", self.path, dict(self.headers), json.loads(raw)))
                self._reply(*stub.post)

            def do_GET(self):
                stub.requests.append(("GET", self.path, dict(self.headers), None))
                self._reply(*(stub.gets.pop(0) if stub.gets else (500, {"message": "exhausted"})))

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"


def run(msg, stub=None, tmp_path=None, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RESEND_", "EMAIL_"))}
    env.update({"RESEND_API_KEY": "re_test", "EMAIL_TO": "owner@example.com", "EMAIL_FROM": "bot@example.com",
                "EMAIL_STATUS_WAIT": "0", "EMAIL_STATUS_RETRY_WAIT": "0"})
    if stub:
        env["RESEND_API_BASE"] = stub.base
    if tmp_path:
        env["EMAIL_FALLBACK_FILE"] = str(tmp_path / "fallback.md")
    env.update(extra)
    return subprocess.run(["bash", str(EMAIL), msg], env=env, capture_output=True, text=True, timeout=60)


def test_missing_credentials_exit_non_zero_and_name_the_gap(tmp_path):
    r = run("hello", tmp_path=tmp_path, RESEND_API_KEY="", EMAIL_TO="")
    assert r.returncode == 3
    assert "RESEND_API_KEY" in r.stderr and "EMAIL_TO" in r.stderr and "EMAIL_FROM" not in r.stderr
    assert "hello" in (tmp_path / "fallback.md").read_text()


def test_accepted_and_delivered_exits_zero_with_the_resend_id():
    stub = Stub((200, {"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"}),
                [(200, {"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794", "last_event": "delivered"})])
    r = run("stops ok", stub)
    assert r.returncode == 0, r.stderr
    assert "id=49a3999c-0ce1-4ea6-ab68-afcd6dc2e794" in r.stdout and "last_event=delivered" in r.stdout
    post, get = stub.requests
    assert post[1] == "/emails" and post[2]["Authorization"] == "Bearer re_test"
    assert post[3]["to"] == ["owner@example.com"] and post[3]["text"] == "stops ok"
    assert len(post[2]["Idempotency-Key"]) <= 256
    assert get[1] == "/emails/49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"


def test_sent_but_not_yet_delivered_is_accepted():
    stub = Stub((200, {"id": "e1"}), [(200, {"id": "e1", "last_event": "sent"})])
    assert run("x", stub).returncode == 0


def test_bounced_is_a_delivery_failure():
    stub = Stub((200, {"id": "e1"}), [(200, {"id": "e1", "last_event": "bounced"})])
    r = run("x", stub)
    assert r.returncode == 4 and "bounced" in r.stderr


def test_rejected_send_shows_the_resend_error_and_exits_two():
    stub = Stub((401, {"statusCode": 401, "name": "missing_api_key", "message": "Missing API key"}), [])
    r = run("x", stub)
    assert r.returncode == 2 and "missing_api_key" in r.stderr and "401" in r.stderr


def test_send_without_an_id_is_rejected():
    stub = Stub((200, {"ok": True}), [])
    assert run("x", stub).returncode == 2


def test_unverifiable_status_after_retries_exits_five():
    stub = Stub((200, {"id": "e1"}), [(500, {"message": "boom"})] * 3)
    r = run("x", stub)
    assert r.returncode == 5 and "status unverifiable" in r.stderr
    assert sum(1 for q in stub.requests if q[0] == "GET") == 3


def test_empty_message_is_a_usage_error():
    assert run("   ").returncode == 1

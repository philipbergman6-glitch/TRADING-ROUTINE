"""Shared offline fixtures for the coordinator (ADR 0010): a local bare
repository plays `origin`, a stateful stub plays the broker, and a fake clock
lets a lease expire without waiting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.state_store import STATE_FILE, StateStore, replay

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)   # Tuesday, market open
EXPIRES = "2026-12-18T21:00:00Z"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_origin(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("init", "-q", "-b", "main", str(seed), cwd=tmp_path)
    git("config", "user.name", "seed", cwd=seed)
    git("config", "user.email", "seed@example.invalid", cwd=seed)
    (seed / "README.md").write_text("seed\n")
    git("add", ".", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", str(bare), "HEAD:main", cwd=seed)
    return bare


def writer_store(tmp_path: Path, origin: Path, name: str) -> StateStore:
    path = tmp_path / name
    git("clone", "-q", str(origin), str(path), cwd=tmp_path)
    git("config", "user.name", name, cwd=path)
    git("config", "user.email", f"{name}@example.invalid", cwd=path)
    return StateStore(path)


def fresh_stores(tmp_path: Path):
    """An open_store stand-in: every call gets its own empty bare-repo store.
    For tests that pin broker-side behaviour one call at a time."""
    count = iter(range(10_000))

    def open_store(environ=None):
        root = tmp_path / f"store{next(count)}"
        shutil.copytree(_template(), root, symlinks=True)
        git("remote", "set-url", "origin", str(root / "origin.git"), cwd=root / "routine")
        return StateStore(root / "routine")
    return open_store


_TEMPLATE: list[Path] = []


def _template() -> Path:
    """One bare origin + writer clone per test session, copied per store (git init is the slow part)."""
    if not _TEMPLATE:
        root = Path(tempfile.mkdtemp(prefix="state-template-"))
        writer_store(root, make_origin(root), "routine")
        _TEMPLATE.append(root)
    return _TEMPLATE[0]


def stored(origin: Path) -> list[dict]:
    listed = git("ls-tree", "main", "--", STATE_FILE, cwd=origin)
    return replay(git("show", f"main:{STATE_FILE}", cwd=origin)) if listed.strip() else []


def intent_lines(origin: Path, intent: str | None = None) -> list[dict]:
    return [e for e in stored(origin) if e["kind"] == "intent" and (intent is None or e["intent"] == intent)]


class Clock:
    """Wall time that only moves when slept on or advanced."""

    def __init__(self, now: datetime = NOW):
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


OPEN = {"new", "accepted", "pending_new", "held", "partially_filled", "pending_cancel"}


class Broker:
    """A paper account small enough to reason about: orders by id and client id,
    positions, and switches for the failures the coordinator must survive."""

    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.positions: dict[str, dict] = {}
        self.posts: list[dict] = []
        self.cancels: list[str] = []
        self.lose_responses = 0      # next N POSTs land, but the caller gets no answer
        self.hidden_lookups = 0      # landed orders stay invisible to the next N lookups
        self.buy_status = "accepted"
        self.buy_filled_qty = None   # e.g. "4" for a partial fill
        self.sell_fills = True       # a market sell fills at once and removes the position
        self.fail_reads = False
        self._n = 0

    # setup ---------------------------------------------------------------------
    def hold(self, symbol, qty, price="100"):
        self.positions[symbol] = {"symbol": symbol, "qty": str(qty),
                                  "market_value": str(int(qty) * int(price))}

    def stop(self, symbol, qty, stop_price, status="new", type="stop", cid=None):
        self._n += 1
        oid = f"stop-{self._n}"
        self.orders[oid] = {"id": oid, "client_order_id": cid or f"auto-{oid}", "symbol": symbol,
                            "side": "sell", "type": type, "qty": str(qty), "filled_qty": "0",
                            "stop_price": str(stop_price), "status": status, "time_in_force": "gtc",
                            "expires_at": EXPIRES}
        return oid

    def by_client(self, cid):
        return next((o for o in self.orders.values() if o["client_order_id"] == cid), None)

    # adapter surface -----------------------------------------------------------
    def read(self, command, arg=None, *rest):
        if self.fail_reads:
            raise SystemExit(4)
        if command == "positions":
            return [dict(p) for p in self.positions.values()]
        if command == "orders":
            assert arg == "open"
            return [dict(o) for o in self.orders.values() if o["status"] in OPEN]
        if command == "order-info":
            got = self.orders.get(arg)
            return dict(got) if got else None
        if command == "order-by-client":
            got = self.by_client(arg)
            if got is not None and self.hidden_lookups > 0:
                self.hidden_lookups -= 1
                return None
            return dict(got) if got else None
        raise AssertionError(f"unexpected read {command} {arg}")

    def run(self, command, arg):
        if command == "cancel":
            self.cancels.append(arg)
            self.orders[arg]["status"] = "canceled"
            return True, "200", "{}", ""
        assert command == "order", command
        body = json.loads(arg)
        self.posts.append(body)
        if self.by_client(body["client_order_id"]) is not None:
            return False, "422", "", '{"code":40010001,"message":"client_order_id must be unique"}'
        self._n += 1
        oid = f"ord-{self._n}"
        order = {"id": oid, "filled_qty": "0", "time_in_force": "gtc", **body}
        if body["side"] == "buy":
            order["status"] = self.buy_status
            if self.buy_filled_qty is not None:
                order["filled_qty"] = self.buy_filled_qty
        elif body["type"] == "market" and self.sell_fills:
            order.update(status="filled", filled_qty=body["qty"])
            self.positions.pop(body["symbol"], None)
        else:
            order.update(status="new", expires_at=EXPIRES)
        self.orders[oid] = order
        if self.lose_responses > 0:
            self.lose_responses -= 1
            return False, "000", "", "adapter timed out; outcome unknown"
        return True, "200", json.dumps(order), ""

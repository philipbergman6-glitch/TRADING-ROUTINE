"""Postgres event ledger: the immutable record of the order lifecycle.

Not the system of record for the bot's working state -- that is still
`memory/*.md`. See ARCHITECTURE.md for why the two are kept apart.

Live path (T4): `persist_decision` / `persist_broker_response` in
`ledger.live_path` are the mandatory write seam for validate_order and
post-submit recording. They do not make the ledger authoritative (#28) or
bind validate→submit (#19).
"""

from .live_path import (
    DEFAULT_STRATEGY_VERSION,
    EXIT_LEDGER,
    LEDGER_DISABLED_WARNING,
    ledger_enabled,
    open_live_ledger,
    persist_broker_response,
    persist_decision,
)

_STORE_NAMES = ("Ledger", "LedgerOrder", "connect", "migrate")


def __getattr__(name: str):  # noqa: ANN202 -- lazy: store needs the psycopg extra
    if name in _STORE_NAMES:
        from . import store

        return getattr(store, name)
    raise AttributeError(f"module 'ledger' has no attribute {name!r}")

__all__ = [
    "DEFAULT_STRATEGY_VERSION",
    "EXIT_LEDGER",
    "LEDGER_DISABLED_WARNING",
    "Ledger",
    "LedgerOrder",
    "connect",
    "ledger_enabled",
    "migrate",
    "open_live_ledger",
    "persist_broker_response",
    "persist_decision",
]

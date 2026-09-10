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
    open_live_ledger,
    persist_broker_response,
    persist_decision,
)
from .store import Ledger, LedgerOrder, connect, migrate

__all__ = [
    "DEFAULT_STRATEGY_VERSION",
    "EXIT_LEDGER",
    "Ledger",
    "LedgerOrder",
    "connect",
    "migrate",
    "open_live_ledger",
    "persist_broker_response",
    "persist_decision",
]

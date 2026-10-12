"""Execution identity (ADR 0005): an intent is minted once and resolved across
reruns and midnight; its attempts are client order ids that are never reused."""
from datetime import date, datetime, timezone

import pytest

from scripts.execution_identity import (MAX_RETRIES, MAX_SEQ, attempt_id, mint_intent, next_free_intent,
                                        parse_intent, resolve_intent)

NOW = datetime(2026, 10, 12, 0, 20, tzinfo=timezone.utc)   # just after UTC midnight
TODAY, YESTERDAY = "20261012", "20261011"


def broker(**orders):
    by_client = {cid.replace("_", "-"): {"id": cid, "status": status} for cid, status in orders.items()}
    reads = []

    def read(command, cid):
        assert command == "order-by-client"
        reads.append(cid)
        return by_client.get(cid)
    read.reads = reads
    return read


def test_intent_ids_are_kind_mint_day_symbol_and_optional_seq():
    assert mint_intent("cl", "amd", date(2026, 10, 12)) == "cl-20261012-AMD"
    assert mint_intent("en", "AMD", date(2026, 10, 12), "2") == "en-20261012-AMD-2"
    assert attempt_id("cl-20261012-AMD", 0) == "cl-20261012-AMD"
    assert attempt_id("cl-20261012-AMD", 3) == "cl-20261012-AMD-r3"
    assert parse_intent("en-20261011-AMD-b", "en", "AMD") == ("en", date(2026, 10, 11), "AMD", "b")


@pytest.mark.parametrize("bad", ["r1", "R12", "bad tag", "toolongtag", ""])
def test_a_seq_that_could_read_as_an_attempt_suffix_or_is_malformed_is_rejected(bad):
    with pytest.raises(ValueError):
        mint_intent("en", "AMD", date(2026, 10, 12), bad)


@pytest.mark.parametrize("intent, why", [
    ("cl-20261012-AMD", "kind"),            # an entry helper given a close intent
    ("en-20261012-NVDA", "symbol"),
    ("en-20261312-AMD", "date"),
    ("en-20261013-AMD", "future"),
    ("en-20261012-AMD-r2", "attempt"),      # an attempt id is not an intent id
    ("en-2026-AMD", "format"),
])
def test_explicit_intent_must_name_this_kind_symbol_and_a_real_past_day(intent, why):
    with pytest.raises(ValueError, match=why):
        resolve_intent(broker(), "en", "AMD", NOW, intent=intent)


def test_fresh_intent_is_minted_for_today_when_nothing_exists():
    got = resolve_intent(broker(), "cl", "AMD", NOW)
    assert (got.intent, got.client_order_id, got.order) == (f"cl-{TODAY}-AMD", f"cl-{TODAY}-AMD", None)


def test_dead_attempts_are_skipped_never_reused():
    read = broker(**{f"en_{TODAY}_AMD": "rejected", f"en_{TODAY}_AMD_r1": "canceled"})
    got = resolve_intent(read, "en", "AMD", NOW, dead={"rejected", "canceled"})
    assert got.intent == f"en-{TODAY}-AMD" and got.client_order_id == f"en-{TODAY}-AMD-r2"
    assert [d["status"] for d in got.dead] == ["rejected", "canceled"] and got.order is None


def test_every_attempt_dead_is_exhausted_not_a_silent_new_id():
    read = broker(**{f"cl_{TODAY}_AMD" + (f"_r{n}" if n else ""): "rejected" for n in range(MAX_RETRIES + 1)})
    got = resolve_intent(read, "cl", "AMD", NOW)
    assert got.exhausted and got.client_order_id is None


def test_unexpected_attempt_status_is_a_hard_failure():
    with pytest.raises(ValueError, match="pending_cancel"):
        resolve_intent(broker(**{f"cl_{TODAY}_AMD": "pending_cancel"}), "cl", "AMD", NOW)


def test_live_attempt_from_yesterday_is_adopted_across_midnight():
    read = broker(**{f"cl_{YESTERDAY}_AMD": "rejected", f"cl_{YESTERDAY}_AMD_r1": "accepted"})
    got = resolve_intent(read, "cl", "AMD", NOW)
    assert got.intent == f"cl-{YESTERDAY}-AMD" and got.live
    assert got.client_order_id == f"cl-{YESTERDAY}-AMD-r1"


def test_terminal_attempts_from_yesterday_are_history_not_adopted():
    read = broker(**{f"en_{YESTERDAY}_AMD": "filled", f"cl_{YESTERDAY}_AMD": "rejected"})
    assert resolve_intent(read, "en", "AMD", NOW).intent == f"en-{TODAY}-AMD"
    assert resolve_intent(read, "cl", "AMD", NOW).client_order_id == f"cl-{TODAY}-AMD"


def test_explicit_intent_resolves_on_any_later_day_including_its_dead_attempts():
    read = broker(**{f"cl_{YESTERDAY}_AMD": "rejected"})
    got = resolve_intent(read, "cl", "AMD", NOW, intent=f"cl-{YESTERDAY}-AMD")
    assert got.intent == f"cl-{YESTERDAY}-AMD" and got.client_order_id == f"cl-{YESTERDAY}-AMD-r1"


def test_latest_intent_of_today_is_resolved_and_the_next_seq_is_known():
    read = broker(**{f"cl_{TODAY}_AMD": "filled", f"cl_{TODAY}_AMD_2": "filled"})
    got = resolve_intent(read, "cl", "AMD", NOW)
    assert got.intent == f"cl-{TODAY}-AMD-2" and got.filled
    assert next_free_intent(read, "cl", "AMD", NOW) == f"cl-{TODAY}-AMD-3"


def test_tag_names_one_intent_and_ignores_the_untagged_family():
    read = broker(**{f"en_{TODAY}_AMD": "filled"})
    got = resolve_intent(read, "en", "AMD", NOW, tag="b")
    assert got.intent == f"en-{TODAY}-AMD-b" and got.order is None


def test_sequence_space_is_bounded():
    read = broker(**{f"cl_{TODAY}_AMD" + (f"_{s}" if s > 1 else ""): "filled" for s in range(1, MAX_SEQ + 1)})
    assert resolve_intent(read, "cl", "AMD", NOW).filled
    assert next_free_intent(read, "cl", "AMD", NOW) is None

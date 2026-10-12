"""Protection-check service level: the newest successful check must never be
older than MAX_DELAY while the exchange is open (ADR 0007)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.protection_sla import MAX_DELAY, session_window, staleness_breaches

DAY = date(2026, 10, 7)  # Wed, EDT: 09:30-16:00 ET = 13:30-20:00Z
Z = timezone.utc


def t(h, m=0):
    return datetime(2026, 10, 7, h, m, tzinfo=Z)


def test_level_is_ninety_minutes():
    assert MAX_DELAY == timedelta(minutes=90)


def test_session_window_is_exchange_hours_in_utc():
    assert session_window(DAY) == (t(13, 30), t(20, 0))


def test_checks_every_thirty_minutes_meet_the_level():
    checks = [t(13, 0) + timedelta(minutes=30 * i) for i in range(16)]
    assert staleness_breaches(checks, DAY, now=t(22)) == []


def test_observed_2026_10_07_first_check_at_19_15z_breaches_from_15_00z():
    # Research 0008: Wed 10-07 first success 19:15Z, 5.75 h after the open.
    # Last success the day before was 22:30Z; its age passes 90 min long
    # before the open, so the breach starts at the open and ends at 19:15Z.
    checks = [datetime(2026, 10, 6, 22, 30, tzinfo=Z), t(19, 15), t(22, 20)]
    assert staleness_breaches(checks, DAY, now=t(23)) == [
        {"from": "2026-10-07T13:30:00+00:00", "to": "2026-10-07T19:15:00+00:00", "minutes": 345}]


def test_gap_inside_the_session_starts_ninety_minutes_after_the_last_check():
    checks = [t(13, 30), t(17, 0), t(19, 30)]
    assert staleness_breaches(checks, DAY, now=t(22)) == [
        {"from": "2026-10-07T15:00:00+00:00", "to": "2026-10-07T17:00:00+00:00", "minutes": 120},
        {"from": "2026-10-07T18:30:00+00:00", "to": "2026-10-07T19:30:00+00:00", "minutes": 60}]


def test_no_check_all_day_is_one_breach_for_the_whole_session():
    assert staleness_breaches([], DAY, now=t(22)) == [
        {"from": "2026-10-07T13:30:00+00:00", "to": "2026-10-07T20:00:00+00:00", "minutes": 390}]


def test_breach_still_open_ends_at_now_when_measured_mid_session():
    checks = [t(13, 30)]
    assert staleness_breaches(checks, DAY, now=t(16, 0)) == [
        {"from": "2026-10-07T15:00:00+00:00", "to": "2026-10-07T16:00:00+00:00", "minutes": 60}]


def test_naive_or_unsorted_input_is_rejected():
    with pytest.raises(ValueError):
        staleness_breaches([datetime(2026, 10, 7, 14, 0)], DAY, now=t(22))
    with pytest.raises(ValueError):
        staleness_breaches([t(13, 30)], DAY, now=datetime(2026, 10, 7, 22, 0))

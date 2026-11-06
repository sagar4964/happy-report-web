"""Date logic for the contributions page. No database needed."""
from datetime import date, datetime, timedelta, timezone
from app.contributions.periods import (period_bounds, to_utc, period_label, neighbours, parse_anchor,
                                       today_in_nepal)

UTC = timezone.utc


def test_a_week_runs_sunday_to_saturday():
    assert period_bounds("week", date(2026, 11, 5)) == (date(2026, 11, 1), date(2026, 11, 8))   # Thursday
    assert period_bounds("week", date(2026, 11, 1)) == (date(2026, 11, 1), date(2026, 11, 8))   # Sunday
    assert period_bounds("week", date(2026, 11, 7)) == (date(2026, 11, 1), date(2026, 11, 8))   # Saturday
    assert period_bounds("week", date(2026, 11, 8)) == (date(2026, 11, 8), date(2026, 11, 15))  # next Sunday


def test_months_and_years():
    assert period_bounds("month", date(2026, 11, 15)) == (date(2026, 11, 1), date(2026, 12, 1))
    assert period_bounds("month", date(2026, 12, 31)) == (date(2026, 12, 1), date(2027, 1, 1))
    assert period_bounds("month", date(2028, 2, 29)) == (date(2028, 2, 1), date(2028, 3, 1))
    assert period_bounds("year", date(2026, 6, 1)) == (date(2026, 1, 1), date(2027, 1, 1))


def test_boundaries_are_measured_in_nepal_time():
    start_of_november = to_utc(date(2026, 11, 1))
    assert start_of_november == datetime(2026, 10, 31, 18, 15, tzinfo=UTC)
    assert datetime(2026, 10, 31, 19, 0, tzinfo=UTC) >= start_of_november      # 00:45 on 1 Nov in Nepal
    assert datetime(2026, 10, 31, 18, 0, tzinfo=UTC) < start_of_november       # 23:45 on 31 Oct in Nepal


def test_today_in_nepal_can_be_a_day_ahead_of_utc():
    assert today_in_nepal(datetime(2026, 11, 4, 20, 0, tzinfo=UTC)) == date(2026, 11, 5)
    assert today_in_nepal(datetime(2026, 11, 4, 10, 0, tzinfo=UTC)) == date(2026, 11, 4)


def test_labels():
    assert period_label("month", date(2026, 11, 1), date(2026, 12, 1)) == "November 2026"
    assert period_label("year", date(2026, 1, 1), date(2027, 1, 1)) == "2026"
    assert period_label("week", date(2026, 11, 1), date(2026, 11, 8)) == "Sun 01 Nov 2026 to Sat 07 Nov 2026"


def test_earlier_and_later_links():
    start, end = date(2026, 11, 1), date(2026, 12, 1)
    before, after = neighbours(start, end, today=date(2026, 11, 20))
    assert before == date(2026, 10, 31) and after is None          # no "later" for the current period
    before, after = neighbours(start, end, today=date(2027, 3, 1))
    assert after == date(2026, 12, 1)                              # a finished period has a next one


def test_bad_or_future_dates_fall_back_to_today():
    today = date(2026, 11, 5)
    assert parse_anchor("2026-10-01", today) == date(2026, 10, 1)
    assert parse_anchor("2030-01-01", today) == today
    assert parse_anchor("garbage", today) == today
    assert parse_anchor(None, today) == today

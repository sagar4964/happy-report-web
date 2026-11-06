"""Date helpers for the contributions page (no database, easy to test).

Weeks run Sunday to Saturday and every period is measured in Nepal time (UTC+5:45),
because the database stores times in UTC.
"""
from datetime import date, datetime, timedelta, timezone

NEPAL_OFFSET = timedelta(hours=5, minutes=45)
VIEWS = ("week", "month", "year")


def today_in_nepal(now=None):
    now = now or datetime.now(timezone.utc)
    return (now + NEPAL_OFFSET).date()


def period_bounds(view, anchor):
    """First day (included) and the day after the last day (excluded), as Nepal dates."""
    if view == "week":
        start = anchor - timedelta(days=(anchor.weekday() + 1) % 7)   # back to the Sunday
        return start, start + timedelta(days=7)
    if view == "year":
        return date(anchor.year, 1, 1), date(anchor.year + 1, 1, 1)
    start = anchor.replace(day=1)
    return start, (start + timedelta(days=32)).replace(day=1)


def to_utc(local_date):
    """Midnight at the start of this Nepal date, expressed in UTC (what the database stores)."""
    return datetime(local_date.year, local_date.month, local_date.day, tzinfo=timezone.utc) - NEPAL_OFFSET


def period_label(view, start, end):
    if view == "week":
        last = end - timedelta(days=1)
        return f"{start.strftime('%a %d %b %Y')} to {last.strftime('%a %d %b %Y')}"
    if view == "year":
        return str(start.year)
    return start.strftime("%B %Y")


def neighbours(start, end, today):
    """A date inside the previous period, and one inside the next period (None if it is in the future)."""
    previous_anchor = start - timedelta(days=1)
    next_anchor = end if end <= today else None
    return previous_anchor, next_anchor


def parse_anchor(text, today):
    try:
        value = date.fromisoformat(text)
    except (TypeError, ValueError):
        return today
    return min(value, today)

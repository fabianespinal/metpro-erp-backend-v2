"""Business dates in Dominican Republic time (debug pass B-04, approved 2026-10-18).

The database and the server run in UTC. Without this, a document created after
8 PM in Santo Domingo carried the next day's date.

Rules:
- New document dates (invoice date, project start date) use business_today().
- quotes.created_at is a naive UTC timestamp; local_date() turns it into the
  Santo Domingo calendar date for PDFs.
- invoices.invoice_date already stores the intended calendar date (midnight UTC),
  so it is printed as stored and must NOT be converted.
- Stored timestamps and history are not changed.

Toggle: BUSINESS_TZ env var (default America/Santo_Domingo). Set BUSINESS_TZ=UTC
to restore the previous behaviour without a deploy of code.
"""
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_BUSINESS_TZ = "America/Santo_Domingo"


def business_tz_name() -> str:
    return (os.environ.get("BUSINESS_TZ") or DEFAULT_BUSINESS_TZ).strip() or DEFAULT_BUSINESS_TZ


def business_tz() -> ZoneInfo:
    return ZoneInfo(business_tz_name())


def business_today(now: datetime = None) -> date:
    """Today's calendar date in the business time zone."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(business_tz()).date()


def local_date(value) -> str:
    """YYYY-MM-DD in the business time zone for a stored timestamp.

    Naive datetimes are UTC (database TimeZone=UTC). Dates pass through unchanged.
    Strings fall back to their first 10 characters (previous behaviour). Empty -> "".
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(business_tz()).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def sql_local_date(column: str) -> str:
    """SQL expression: the business-time calendar date of a naive-UTC timestamp column.

    Use with one bind parameter for the zone name: params.append(business_tz_name()).
    """
    return f"(({column} AT TIME ZONE 'UTC') AT TIME ZONE %s)::date"

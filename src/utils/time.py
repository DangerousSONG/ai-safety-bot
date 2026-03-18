from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Asia/Shanghai"


def now_in_tz(tz_name: str = DEFAULT_TZ) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def today_ymd(tz_name: str = DEFAULT_TZ) -> str:
    return now_in_tz(tz_name).strftime("%Y-%m-%d")


def format_dt(dt: datetime | None, tz_name: str = DEFAULT_TZ) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")


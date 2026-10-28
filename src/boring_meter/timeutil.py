"""Timestamp parsing, timezone handling, and reporting periods."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Optional

from boring_meter.errors import BMError


def resolve_timezone(name: str = "") -> tzinfo:
    """Return the configured IANA timezone, or the system's local timezone."""
    if not name:
        # Prefer the system's IANA zone (DST aware) when /etc/localtime names one.
        try:
            import os
            from zoneinfo import ZoneInfo

            real = os.path.realpath("/etc/localtime")
            if "zoneinfo/" in real:
                return ZoneInfo(real.split("zoneinfo/", 1)[1])
        except Exception:
            pass
        return datetime.now().astimezone().tzinfo or timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        raise BMError(
            "INVALID_CONFIG",
            "Unknown timezone '%s'." % name,
            "Use an IANA name such as America/New_York, or clear it: boring-meter settings set time.timezone ''",
        )


def parse_ts(value) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Naive timestamps are rejected (None) instead of guessing their offset.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Python < 3.11 rejects some fractional second widths; trim to microseconds.
        try:
            head, _, tail = text.partition(".")
            frac = ""
            rest = tail
            while rest and rest[0].isdigit():
                frac += rest[0]
                rest = rest[1:]
            parsed = datetime.fromisoformat(head + "." + (frac + "000000")[:6] + rest)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass
class Period:
    start: Optional[datetime]  # inclusive, aware UTC; None means unbounded
    end: Optional[datetime]  # exclusive, aware UTC; None means unbounded
    label: str
    kind: str
    tz_name: str

    def contains(self, ts: Optional[datetime]) -> bool:
        if ts is None:
            return False
        if self.start is not None and ts < self.start:
            return False
        if self.end is not None and ts >= self.end:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "timezone": self.tz_name,
            "boundary_semantics": "start inclusive, end exclusive; calendar days use the timezone shown",
        }


def _midnight(day: date, tz: tzinfo) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)


def _tz_label(tz: tzinfo, now: datetime) -> str:
    key = getattr(tz, "key", None)
    if key:
        return key
    return now.astimezone(tz).strftime("UTC%z")


def _parse_day(text: str, flag: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise BMError("INVALID_ARGUMENT", "%s expects a date like 2026-10-01, got '%s'." % (flag, text))


def resolve_period(
    *,
    today: bool = False,
    week: bool = False,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    all_time: bool = False,
    default_days: int = 7,
    tz: tzinfo,
    now: Optional[datetime] = None,
) -> Period:
    now = now or datetime.now(timezone.utc)
    local_today = now.astimezone(tz).date()
    tz_name = _tz_label(tz, now)
    chosen = [bool(today), bool(week), days is not None, bool(since or until), bool(all_time)]
    if sum(chosen) > 1:
        raise BMError("INVALID_ARGUMENT", "Choose only one of --today, --week, --days, --since/--until, --all.")
    if all_time:
        return Period(None, None, "All available records", "all", tz_name)
    if since or until:
        start_day = _parse_day(since, "--since") if since else None
        end_day = _parse_day(until, "--until") if until else None
        if start_day and end_day and end_day < start_day:
            raise BMError("INVALID_ARGUMENT", "--until is earlier than --since.")
        start = _midnight(start_day, tz) if start_day else None
        end = _midnight(end_day + timedelta(days=1), tz) if end_day else None
        label = "%s to %s (%s)" % (start_day or "earliest", end_day or "now", tz_name)
        return Period(start, end, label, "range", tz_name)
    if today:
        return Period(_midnight(local_today, tz), None, "Today, %s (%s)" % (local_today, tz_name), "today", tz_name)
    count = 7 if week else (days if days is not None else default_days)
    if count < 1:
        raise BMError("INVALID_ARGUMENT", "--days must be at least 1.")
    first = local_today - timedelta(days=count - 1)
    label = "Last %d calendar day%s, %s to %s (%s)" % (count, "" if count == 1 else "s", first, local_today, tz_name)
    return Period(_midnight(first, tz), None, label, "days", tz_name)


def local_day(ts: datetime, tz: tzinfo) -> str:
    return ts.astimezone(tz).date().isoformat()

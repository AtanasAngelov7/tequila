"""Lightweight cron expression parser for Tequila v2 scheduler (§7.1).

Supports the standard 5-field cron format:
    minute  hour  dom  month  dow

Field ranges:
    minute  0–59
    hour    0–23
    dom     1–31
    month   1–12
    dow     0–7  (0 and 7 = Sunday)

Supported syntax per field:
    *           — every value
    n           — specific value
    a-b         — range
    */n         — step over full range
    a-b/n       — step over range
    a,b,c       — list

Does NOT support @yearly/@monthly macros or L/W/# specifiers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Field parsing ─────────────────────────────────────────────────────────────


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """Return the set of integers that a cron field matches."""
    result: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if part == "*":
            for v in range(lo, hi + 1, step):
                result.add(v)
        elif "-" in part:
            a, b = part.split("-", 1)
            for v in range(int(a), int(b) + 1, step):
                result.add(v)
        else:
            v = int(part)
            result.add(v)
    return result


def _parse_expr(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    """Parse cron expression into (minutes, hours, doms, months, dows)."""
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Expected 5 cron fields, got {len(fields)!r} in {expr!r}")
    mins = _parse_field(fields[0], 0, 59)
    hrs = _parse_field(fields[1], 0, 23)
    doms = _parse_field(fields[2], 1, 31)
    months = _parse_field(fields[3], 1, 12)
    dows_raw = _parse_field(fields[4], 0, 7)
    # Normalise: 7 → 0 (both mean Sunday)
    dows = {0 if d == 7 else d for d in dows_raw}
    return mins, hrs, doms, months, dows


# ── Public API ────────────────────────────────────────────────────────────────


def validate_cron(expr: str) -> bool:
    """Return True if expr is a valid 5-field cron expression."""
    try:
        _parse_expr(expr)
        return True
    except (ValueError, IndexError):
        return False


def next_run(expr: str, after: datetime | None = None) -> datetime:
    """Return the next datetime (UTC) that matches the cron expression.

    Scans minute-by-minute from ``after`` (default = now) up to 4 years
    ahead.  Raises ``ValueError`` if no matching time is found in that
    window (practically impossible for any valid expression).
    """
    mins, hrs, doms, months, dows = _parse_expr(expr)

    # Start one minute after the reference point
    ref = after or datetime.now(tz=timezone.utc)
    # Strip seconds/microseconds, advance by 1 minute
    ref = ref.replace(second=0, microsecond=0) + timedelta(minutes=1)

    limit = ref + timedelta(days=365 * 4)
    cursor = ref

    while cursor < limit:
        # Fast-forward month
        if cursor.month not in months:
            if cursor.month == 12:
                cursor = cursor.replace(year=cursor.year + 1, month=1, day=1, hour=0, minute=0)
            else:
                cursor = cursor.replace(month=cursor.month + 1, day=1, hour=0, minute=0)
            continue
        # Fast-forward day-of-month and day-of-week
        if cursor.day not in doms or cursor.weekday() not in dows:
            cursor = cursor.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        # Fast-forward hour
        if cursor.hour not in hrs:
            cursor = cursor.replace(minute=0) + timedelta(hours=1)
            continue
        # Fast-forward minute
        if cursor.minute not in mins:
            cursor += timedelta(minutes=1)
            continue
        return cursor

    raise ValueError(f"No matching time found for cron expression {expr!r} within 4 years")

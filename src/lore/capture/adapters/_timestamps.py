"""Timestamp normalization shared by every capture adapter.

Every adapter faces the same invariant: a source record may omit its timestamp
(older, edited, or third-party artifacts) and a present timestamp may lack a
zone. Both must yield a timezone-aware UTC datetime, or the actuation lifecycle
(which subtracts `now` in UTC) crashes with a naive-vs-aware TypeError far
downstream of the adapter that let the value through.
"""

from __future__ import annotations

from datetime import datetime, timezone

EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def parse_ts(raw: str | None) -> datetime:
    """Parse an ISO-8601 string into an aware UTC datetime, tolerating absence."""
    if not raw:
        return EPOCH
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return EPOCH
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

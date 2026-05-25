"""The actuation loop's lifecycle (C0 lever 2).

A knowledge layer's value is an actuation property, not a storage property. Left
alone, a compiled store grows monotonically and rots into a dumpyard. Usage —
recorded by the serve layer — drives a homeostatic lifecycle so the *active* set
plateaus and churns:

- never-served claims past a staleness window decay to `archived`;
- claims overridden in real use (wrong/stale) are retired;
- claims that proved influential are reinforced (authority up).

Run this periodically (e.g. after each compile, or on a cron) over the store.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from lore.schemas import Claim

_REINFORCE_PER_INFLUENCE = 0.1


def apply_lifecycle(
    claims: list[Claim],
    *,
    now: datetime,
    max_unused_age: timedelta,
    override_threshold: int = 2,
) -> list[Claim]:
    out: list[Claim] = []
    for c in claims:
        out.append(_step(c, now, max_unused_age, override_threshold))
    return out


def _step(c: Claim, now: datetime, max_unused_age: timedelta, override_threshold: int) -> Claim:
    if c.status != "active":
        return c

    u = c.usage
    # Retired by real-use contradiction.
    if u.times_overridden >= override_threshold and u.times_overridden > u.times_influential:
        return c.model_copy(update={"status": "archived"})

    # Never used and stale -> decay out of the active set.
    if u.times_served == 0 and c.observed_at is not None and (now - c.observed_at) > max_unused_age:
        return c.model_copy(update={"status": "archived"})

    # Used and valued -> reinforce.
    if u.times_influential > 0:
        boosted = min(1.0, c.authority + _REINFORCE_PER_INFLUENCE * u.times_influential)
        return c.model_copy(update={"authority": boosted})

    return c

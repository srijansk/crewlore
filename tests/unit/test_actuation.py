"""C0 lever 2 — usage drives lifecycle. Unused stale claims decay to archived,
claims overridden in real use are retired, and influential claims are reinforced.
This is what keeps the store churning (count plateaus) instead of growing into a
dumpyard. The health signal is: applying the loop never grows the active set.
"""

from datetime import datetime, timedelta, timezone

from lore.actuation import apply_lifecycle
from lore.schemas import Anchor, Claim, Provenance, UsageStats

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def _claim(statement, *, observed_days_ago=1, usage=None, authority=0.5, status="active"):
    return Claim(
        statement=statement, kind="gotcha", scope="services/billing",
        authority=authority, status=status,
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=statement)],
        observed_at=NOW - observed_days_ago * DAY,
        usage=usage or UsageStats(),
    )


def test_unused_stale_claim_is_archived():
    claims = [_claim("old unused gotcha", observed_days_ago=60)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "archived"


def test_naive_observed_at_does_not_crash_lifecycle():
    # Regression: a claim with a tz-naive observed_at (e.g. from a timestampless
    # transcript) must not crash the lifecycle's `now - observed_at` subtraction.
    claim = Claim(
        statement="naive-stamped gotcha", kind="gotcha", scope="services/billing",
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote="x")],
        observed_at=datetime(2026, 1, 1),  # NAIVE on purpose
    )
    out = apply_lifecycle([claim], now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "archived"  # old + unused -> decays, no TypeError


def test_recent_unused_claim_is_kept():
    claims = [_claim("recent gotcha", observed_days_ago=5)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "active"


def test_served_claim_is_not_archived_even_if_old():
    used = UsageStats(times_served=3)
    claims = [_claim("old but used", observed_days_ago=60, usage=used)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "active"


def test_overridden_claim_is_archived():
    overridden = UsageStats(times_served=4, times_influential=0, times_overridden=3)
    claims = [_claim("wrong claim", usage=overridden)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY, override_threshold=2)
    assert out[0].status == "archived"


def test_influential_claim_authority_is_reinforced():
    influential = UsageStats(times_served=5, times_influential=2)
    claims = [_claim("good claim", usage=influential, authority=0.5)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "active"
    assert out[0].authority > 0.5


def test_lifecycle_never_grows_the_active_set():
    before_active = 3
    claims = [
        _claim("old unused", observed_days_ago=90),
        _claim("recent", observed_days_ago=2),
        _claim("used", observed_days_ago=90, usage=UsageStats(times_served=1)),
    ]
    assert sum(c.status == "active" for c in claims) == before_active
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert sum(c.status == "active" for c in out) <= before_active

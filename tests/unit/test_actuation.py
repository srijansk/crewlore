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


def _claim(
    statement, *, observed_days_ago=1, compiled_days_ago=None, usage=None,
    authority=0.5, status="active",
):
    # Compiled when observed unless a test says otherwise — that is the
    # live-transcript case, where the two clocks coincide.
    if compiled_days_ago is None:
        compiled_days_ago = observed_days_ago
    return Claim(
        statement=statement, kind="gotcha", scope="services/billing",
        authority=authority, status=status,
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=statement)],
        observed_at=NOW - observed_days_ago * DAY,
        compiled_at=NOW - compiled_days_ago * DAY,
        usage=usage or UsageStats(),
    )


def test_unused_stale_claim_is_archived():
    claims = [_claim("old unused gotcha", observed_days_ago=60)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "archived"


def test_naive_compiled_at_does_not_crash_lifecycle():
    # Regression: a claim with a tz-naive stamp (e.g. from a timestampless
    # transcript) must not crash the lifecycle's `now - compiled_at` subtraction.
    claim = Claim(
        statement="naive-stamped gotcha", kind="gotcha", scope="services/billing",
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote="x")],
        compiled_at=datetime(2026, 1, 1),  # NAIVE on purpose
    )
    out = apply_lifecycle([claim], now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "archived"  # old + unused -> decays, no TypeError


# GUARDS: the bug this fixes. A claim compiled today from a months-old source
# (an imported PR archive, a backfill) must not be archived before it has ever
# been served. If this regresses, importing any historical corpus yields a store
# full of claims, an empty book, and empty retrieval.
def test_claim_from_an_old_session_compiled_today_stays_active():
    claims = [_claim("gotcha from a 2025 pull request",
                     observed_days_ago=300, compiled_days_ago=0)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "active"


# GUARDS: the decay must still bite. A claim that has sat in the store unused
# past the window decays even though its source was recent when captured.
def test_claim_that_sat_unused_in_the_store_still_decays():
    claims = [_claim("never read", observed_days_ago=61, compiled_days_ago=60)]
    out = apply_lifecycle(claims, now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "archived"


# GUARDS: never archive on a clock we do not have. Claims written by an older
# version carry no entry stamp; they get one on the next write rather than being
# silently retired on first sight.
def test_claim_without_an_entry_stamp_is_left_alone():
    claim = Claim(
        statement="legacy claim", kind="gotcha", scope="services/billing",
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    out = apply_lifecycle([claim], now=NOW, max_unused_age=30 * DAY)
    assert out[0].status == "active"


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

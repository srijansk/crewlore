"""Success-criteria measurement.

fidelity_report: every claim's anchor must resolve verbatim against its source
(the spec's fidelity criterion). A claim without a verifiable anchor is a defect.

replay_report: the cheap, honest actuation demo. Compile prior knowledge up to
time T, replay the actual post-T sessions, and count *preventable rediscoveries*
— sessions that re-derived something a prior claim already knew. This measures
value (actuation), not quiz-passing.
"""

from datetime import datetime, timezone

from lore.replay import fidelity_report, replay_report
from lore.schemas import Anchor, Claim, NSFEvent, Provenance


def _claim(statement, *, quote=None):
    return Claim(
        statement=statement, kind="gotcha", scope="services/billing",
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=quote or statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


def _session(text):
    return [
        NSFEvent(
            session="p", actor="user", kind="user_message",
            timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc), content=text,
        )
    ]


def test_fidelity_is_full_when_all_anchors_resolve():
    claims = [_claim("dedupe billing webhook", quote="webhook fires twice")]
    source = "earlier the agent noted the webhook fires twice in staging"
    report = fidelity_report(claims, source)
    assert report.rate == 1.0
    assert report.defects == []


def test_fidelity_flags_unresolvable_anchor():
    claims = [_claim("fabricated claim", quote="this never appeared anywhere")]
    report = fidelity_report(claims, "totally unrelated transcript text")
    assert report.rate == 0.0
    assert len(report.defects) == 1


def test_preventable_rediscovery_counted_when_prior_claim_matches():
    prior = [_claim("dedupe billing webhook on idempotency key")]
    post = {"ses_post": _session("why does the billing webhook fire twice?")}
    report = replay_report(prior, post)
    assert report.preventable == 1
    assert report.total == 1
    assert report.rate == 1.0
    assert report.hits["ses_post"] == prior[0].id


def test_session_with_no_prior_match_is_not_preventable():
    prior = [_claim("dedupe billing webhook on idempotency key")]
    post = {"ses_post": _session("how do I configure kubernetes ingress?")}
    report = replay_report(prior, post)
    assert report.preventable == 0
    assert report.rate == 0.0


def test_shared_stopwords_do_not_create_false_matches():
    # Regression: an unrelated session must not count as preventable just because
    # it shares a stopword (e.g. "do"/"the") with a claim's action text.
    prior = [_claim("Run migrations before deploy; do not edit generated files.")]
    post = {"k8s": _session("how do I configure the kubernetes ingress controller?")}
    report = replay_report(prior, post)
    assert report.preventable == 0


def test_rate_is_preventable_over_total():
    prior = [_claim("dedupe billing webhook on idempotency key")]
    post = {
        "a": _session("billing webhook firing twice again"),
        "b": _session("unrelated kubernetes ingress question"),
    }
    report = replay_report(prior, post)
    assert report.total == 2
    assert report.preventable == 1
    assert report.rate == 0.5

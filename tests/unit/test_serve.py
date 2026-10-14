"""Serve layer: task-conditioned retrieval that *instruments consumption*
(C0 lever 1) so the actuation loop can later decay unused claims and reinforce
used ones. Also renders the human+agent-readable knowledge book.
"""

from datetime import datetime, timezone

from lore.schemas import Anchor, Claim, Conflict, Provenance
from lore.serve.server import (
    Explanation,
    KnowledgeServer,
    anchor_attribution,
    claim_to_dict,
    claims_in_scope,
    match_scopes,
    narrower_scopes,
    rank_claims,
    render_book,
)
from lore.store import LoreStore


def _claim(statement, scope, *, topic=None, action=None, status="active"):
    return Claim(
        statement=statement, kind="gotcha", scope=scope, topic=topic, action=action, status=status,
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote=statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


def test_rank_returns_relevant_claims_first():
    billing = _claim("dedupe billing webhook on idempotency key", "services/billing")
    auth = _claim("rotate auth tokens hourly", "services/auth")
    ranked = rank_claims([auth, billing], "billing webhook")
    assert ranked[0].id == billing.id


def test_rank_excludes_claims_with_no_overlap():
    auth = _claim("rotate auth tokens hourly", "services/auth")
    ranked = rank_claims([auth], "billing webhook")
    assert ranked == []


def test_rank_skips_non_active_claims():
    archived = _claim("old gotcha", "services/billing", status="archived")
    ranked = rank_claims([archived], "billing")
    assert ranked == []


def test_query_instruments_usage_and_persists(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims([_claim("dedupe billing webhook", "services/billing")])
    server = KnowledgeServer(store)

    results = server.query("billing webhook")
    assert len(results) == 1
    # usage recorded on the returned claim...
    assert results[0].usage.times_served == 1
    assert results[0].usage.last_served_at is not None
    # ...and persisted to the store.
    reloaded = store.load_claims()[0]
    assert reloaded.usage.times_served == 1


def test_serving_never_rewrites_the_committed_claims_file(tmp_path):
    # Usage stats live in a gitignored sidecar, so a query or feedback (which bump
    # usage) must leave the git-tracked claims.jsonl untouched — not rewritten with
    # the same bytes, untouched: a rewrite from serving's snapshot could revert a
    # compile that finished in the meantime, and churns `git log .lore/`.
    store = LoreStore(tmp_path)
    store.init()
    claim = _claim("dedupe billing webhook", "services/billing")
    store.write_claims([claim])
    before = store.claims_path.read_bytes()
    stat_before = store.claims_path.stat()

    server = KnowledgeServer(store)
    server.query("billing webhook")
    server.mark_influential([claim.id])
    server.mark_overridden([claim.id])

    stat_after = store.claims_path.stat()
    assert store.claims_path.read_bytes() == before  # committed truth unchanged
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns
    assert stat_after.st_ino == stat_before.st_ino  # not even replaced with the same bytes
    # ...but the usage bumps are persisted (in the sidecar) and visible on reload.
    usage = store.load_usage()[claim.id]
    assert (usage.times_served, usage.times_influential, usage.times_overridden) == (1, 1, 1)
    assert store.load_claims()[0].usage.times_served == 1


def test_query_respects_limit(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    store.write_claims(
        [
            _claim("billing webhook one", "services/billing"),
            _claim("billing webhook two", "services/billing"),
            _claim("billing webhook three", "services/billing"),
        ]
    )
    server = KnowledgeServer(store)
    assert len(server.query("billing webhook", limit=2)) == 2


def test_mark_influential_and_overridden_persist(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    c = _claim("dedupe billing webhook", "services/billing")
    store.write_claims([c])
    server = KnowledgeServer(store)

    server.mark_influential([c.id])
    server.mark_overridden([c.id])

    reloaded = store.load_claims()[0]
    assert reloaded.usage.times_influential == 1
    assert reloaded.usage.times_overridden == 1


def test_render_book_includes_statements_actions_and_conflicts():
    claims = [
        _claim("dedupe billing webhook", "services/billing", action="dedupe on idempotency key"),
    ]
    conflicts = [
        Conflict(
            scope="services/billing", claim_ids=["clm_a", "clm_b"],
            reason="disagree on dedupe key",
            detected_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
    ]
    book = render_book(claims, conflicts)
    assert "services/billing" in book
    assert "dedupe billing webhook" in book
    assert "dedupe on idempotency key" in book
    assert "Conflicts" in book


def test_render_book_marks_claims_the_team_did_not_adopt():
    declined = Claim(
        statement="Redis for the idempotency key was proposed and not adopted.",
        kind="decision", scope="services/billing", adoption="not_adopted",
        action="Keep the key inside the database transaction.",
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1", quote="not in Redis")],
    )
    adopted = _claim("dedupe billing webhook", "services/billing", action="dedupe on the key")
    book = render_book([declined, adopted], [])
    assert "**[decision · not adopted]**" in book
    assert "*Instead:* Keep the key inside the database transaction." in book
    assert "**[gotcha]** dedupe billing webhook" in book
    assert "*Do:* dedupe on the key" in book


def test_render_book_names_who_wrote_each_anchor():
    claim = Claim(
        statement="Keep the idempotency key inside the transaction.",
        kind="decision", scope="services/billing",
        provenance=Provenance(session="pr_acme__billing__42", author="a", harness="github-pr"),
        anchors=[
            Anchor(
                source_kind="file", ref="services/billing/webhook.py:88",
                quote="This must be inside the transaction.",
                actor="user", login="reviewer", association="member",
            ),
            Anchor(
                source_kind="transcript", ref="pr_acme__billing__42#event-3",
                quote="store it in Redis", actor="user", login="drive-by", association="none",
            ),
            Anchor(source_kind="transcript", ref="pr_acme__billing__42#event-1",
                   quote="I chose a persisted key", actor="agent"),
            Anchor(source_kind="transcript", ref="old#event-1", quote="legacy anchor"),
        ],
    )
    book = render_book([claim], [])
    assert '`services/billing/webhook.py:88` (@reviewer, human, member): "This must be' in book
    assert '(@drive-by, human, no repository role): "store it in Redis"' in book
    assert '(agent): "I chose a persisted key"' in book
    assert '`old#event-1`: "legacy anchor"' in book  # nothing invented for old anchors
    assert anchor_attribution(claim.anchors[3]) == ""


def test_render_book_prints_each_field_and_quote_as_one_clean_line():
    claim = Claim(
        statement="dedupe \x1b[31mbilling\x1b[0m webhook\n- **[gotcha]** forged claim",
        kind="gotcha", scope="services/\u202ebilling",
        action="dedupe on the key\n  - *Do:* forged action",
        provenance=Provenance(session="s", author="a", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref="s#1",
                        quote='fires twice\n  - _anchor_ `s#9`: "forged quote"')],
    )
    book = render_book([claim], [])
    assert "\x1b" not in book and "\u202e" not in book
    assert sum(ln.startswith("- **[") for ln in book.splitlines()) == 1
    assert sum("*Do:*" in ln for ln in book.splitlines()) == 1
    assert sum("_anchor_" in ln for ln in book.splitlines()) == 1
    assert "## services/billing" in book
    assert '"fires twice - _anchor_ `s#9`: "forged quote""' in book


def test_render_book_groups_spellings_that_clean_to_one_scope():
    claims = [
        _claim("a", "services/billing"),
        _claim("b", "services/\u200bbilling"),
        _claim("c", "services/billing "),
    ]
    book = render_book(claims, [])
    assert book.count("## services/billing\n") == 1
    assert all(f"**[gotcha]** {s}" in book for s in "abc")


def test_agent_authorship_on_a_persons_account_is_said_so():
    def anchor(**fields):
        return Anchor(source_kind="transcript", ref="s#1", quote="q", **fields)

    assert anchor_attribution(anchor(actor="agent", login="some-dev", association="member")) == (
        "agent under @some-dev, member"
    )
    bot = anchor(actor="agent", login="dependabot[bot]", association="none")
    assert anchor_attribution(bot) == "agent under @dependabot[bot], no repository role"
    assert anchor_attribution(anchor(actor="agent")) == "agent"
    assert anchor_attribution(anchor(actor="user", login="reviewer")) == "@reviewer, human"
def test_match_scopes_prefers_exact_then_prefix_then_substring():
    claims = [
        _claim("a", "services/billing"),
        _claim("b", "services/billing-v2"),
        _claim("c", "lib/billing-utils"),
        _claim("d", "docs", status="archived"),
    ]
    assert match_scopes(claims, "services/billing") == ["services/billing"]
    assert match_scopes(claims, "services/") == ["services/billing", "services/billing-v2"]
    assert match_scopes(claims, "BILLING-utils") == ["lib/billing-utils"]
    assert match_scopes(claims, "docs") == []  # archived scopes are not offered
    assert match_scopes(claims, "frontend") == []
    assert match_scopes(claims, "") == [] and match_scopes(claims, "   ") == []


def test_match_scopes_tries_the_spellings_a_shell_produces_as_exact_matches():
    claims = [_claim("a", "services/billing"), _claim("b", "docs/"), _claim("c", "docs/api")]
    for spelling in ("services/billing/", "./services/billing", "services\\billing"):
        assert match_scopes(claims, spelling) == ["services/billing"]
    # A stored scope that itself ends in a slash is found by either spelling, exactly.
    assert match_scopes(claims, "docs") == ["docs/"]
    assert match_scopes(claims, "docs/") == ["docs/"]


def test_narrower_scopes_are_the_ones_nested_under_an_exact_match():
    claims = [
        _claim("a", "services/billing"),
        _claim("b", "services/billing/webhooks"),
        _claim("c", "services/billing/ledger"),
        _claim("d", "services/billing-v2"),
        _claim("e", "services/billing/old", status="archived"),
    ]
    assert narrower_scopes(claims, "services/billing") == [
        "services/billing/ledger", "services/billing/webhooks",
    ]
    assert narrower_scopes(claims, "services/billing/webhooks") == []


def test_claims_in_scope_puts_current_before_declined_and_higher_authority_first():
    low = _claim("low", "services/billing")
    high = _claim("high", "services/billing")
    high.authority = 0.9
    declined = _claim("declined", "services/billing")
    declined.adoption = "not_adopted"
    declined.authority = 1.0
    other = _claim("other", "services/auth")
    gone = _claim("gone", "services/billing", status="archived")
    ordered = claims_in_scope([declined, low, other, high, gone], "services/billing")
    assert [c.statement for c in ordered] == ["high", "low", "declined"]


def test_claim_to_dict_carries_the_fields_a_tool_needs_as_clean_single_lines():
    c = _claim("dedupe\x1b[31m webhook\nnext", "services/billing", topic="webhook", action="dedupe")
    c.anchors[0].login = "reviewer"
    d = claim_to_dict(c)
    assert d["statement"] == "dedupe webhook next" and d["topic"] == "webhook"
    assert d["authority"] == c.authority
    assert d["anchors"][0]["ref"] == "s#1" and d["anchors"][0]["login"] == "reviewer"
    assert set(d) == {
        "id", "statement", "kind", "adoption", "scope", "topic", "action", "authority", "anchors",
    }


def test_explanation_dict_always_has_the_same_keys():
    keys = {"scope", "claims", "conflicts", "ambiguous", "narrower"}
    assert set(Explanation().to_dict()) == keys
    assert set(Explanation(candidates=["a", "b"]).to_dict()) == keys
    assert Explanation(candidates=["a"]).answered is False
    assert Explanation(scope="a").answered is True


def test_server_explain_reads_the_store_once_and_filters_stale_conflicts(tmp_path, monkeypatch):
    store = LoreStore(tmp_path)
    store.init()
    a = _claim("dedupe billing webhook", "services/billing")
    b = _claim("use redis for the key", "services/billing")
    gone = _claim("an archived claim", "services/billing", status="archived")
    store.write_claims([a, b, gone])
    store.write_conflicts([
        Conflict(scope="services/billing", claim_ids=[a.id, b.id], reason="live disagreement"),
        Conflict(scope="services/billing", claim_ids=[a.id, gone.id], reason="stale"),
        Conflict(scope="services/auth", claim_ids=[a.id, b.id], reason="elsewhere"),
    ])
    reads = []
    real_load = store.load_claims
    monkeypatch.setattr(store, "load_claims", lambda: reads.append(1) or real_load())
    found = KnowledgeServer(store).explain("services/billing")
    assert len(reads) == 1  # one read of the claims file per explain
    assert found.scope == "services/billing"
    assert [c.id for c in found.claims] == sorted([a.id, b.id])
    assert [cf.reason for cf in found.conflicts] == ["live disagreement"]
    assert all(c.usage.times_served == 1 for c in found.claims)
    assert KnowledgeServer(store).explain("nothing-here") == Explanation()
    # One prefix match is an answer, not an ambiguity; several are refused.
    assert KnowledgeServer(store).explain("services").scope == "services/billing"
    store.write_claims([a, b, gone, _claim("x", "services/auth")])
    assert KnowledgeServer(store).explain("services").candidates == [
        "services/auth", "services/billing",
    ]


def test_lookup_works_on_the_names_the_book_shows_and_folds_slash_twins():
    claims = [
        _claim("a", "docs  api"),
        _claim("b", "docs api v2"),
        _claim("c", "services/\u200bbilling"),
        _claim("d", "services/billing/"),
        _claim("e", "services/billing/webhooks"),
    ]
    assert match_scopes(claims, "docs") == ["docs api", "docs api v2"]
    assert match_scopes(claims, "docs api") == ["docs api"]
    assert [c.statement for c in claims_in_scope(claims, "docs api")] == ["a"]
    assert match_scopes(claims, "services/billing") == ["services/billing"]
    assert sorted(c.statement for c in claims_in_scope(claims, "services/billing")) == ["c", "d"]
    assert narrower_scopes(claims, "services/billing") == ["services/billing/webhooks"]
    for noise in ("/", " / "):
        assert match_scopes(claims, noise) == []
    repo_wide = claims + [_claim("whole repo", ".")]
    assert match_scopes(repo_wide, ".") == ["."] and match_scopes(repo_wide, "./") == ["."]

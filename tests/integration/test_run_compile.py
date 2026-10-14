"""Integration: orchestrate a full compile from captured sessions in a store,
using a fake extractor, and verify claims, conflicts, and the book are written.
"""

import errno
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

import lore.compile.run as run_module
from lore.actuation import apply_lifecycle
from lore.compile.run import (
    CompileInProgress,
    HeadMoved,
    compile_lock,
    current_head,
    run_compile,
    run_render,
)
from lore.schemas import Anchor, Claim, NSFEvent, Provenance
from lore.serve.server import KnowledgeServer
from lore.store import LoreStore


def _signal_session(store, sid, text):
    events = [
        NSFEvent(
            session=sid, actor="user", kind="user_message",
            timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
            content=f"No, that's wrong — {text}",
        )
    ]
    store.write_session(sid, events)


def _claim(statement, sid, *, topic=None, kind="gotcha", adoption="current"):
    return Claim(
        statement=statement, kind=kind, scope="services/billing", topic=topic,
        adoption=adoption,
        provenance=Provenance(session=sid, author="alice", harness="claude-code"),
        anchors=[Anchor(source_kind="transcript", ref=f"{sid}#1", quote=statement)],
        observed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


class DictExtractor:
    def __init__(self, mapping):
        self.mapping = mapping

    def extract(self, events, session_id, known_topics=None):
        return list(self.mapping.get(session_id, []))


def test_run_compile_writes_claims_conflicts_and_book(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    _signal_session(store, "ses_2", "use idempotency key")
    extractor = DictExtractor(
        {
            # One session holds Dynamo current; another records it as tried and
            # declined. That adoption split is the evidence a conflict needs.
            "ses_1": [
                _claim("use Dynamo for ledger", "ses_1", topic="ledger-db", kind="decision")
            ],
            "ses_2": [
                _claim(
                    "Dynamo for the ledger was tried and not adopted", "ses_2",
                    topic="ledger-db", kind="decision", adoption="not_adopted",
                )
            ],
        }
    )

    result = run_compile(store, extractor)

    assert len(result.claims) == 2
    assert len(result.conflicts) == 1
    # persisted
    assert len(store.load_claims()) == 2
    assert len(store.load_conflicts()) == 1
    # book rendered
    book = (tmp_path / ".lore" / "knowledge" / "README.md").read_text()
    assert "ledger" in book.lower()


def test_run_compile_is_idempotent_across_runs(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    extractor = DictExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]})

    first = run_compile(store, extractor)
    second = run_compile(store, extractor)  # prior claims loaded from store
    assert [c.id for c in second.claims] == [c.id for c in first.claims]
    assert len(store.load_claims()) == 1


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


# GUARDS: a rebase fires one post-commit hook per commit. Only one compile may touch
# the store at a time, and the one that steps aside must write nothing.
def test_a_second_compile_steps_aside_while_the_lock_is_held(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    run_compile(store, DictExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]}))
    before = store.claims_path.read_bytes()
    newer = DictExtractor({"ses_1": [_claim("dedupe on the Stripe event id", "ses_1")]})

    with compile_lock(store):
        with pytest.raises(CompileInProgress, match="another compile is running"):
            run_compile(store, newer, rebuild=True)
    assert store.claims_path.read_bytes() == before

    run_compile(store, newer, rebuild=True)  # the lock is released again
    assert len(store.load_claims()) == 2


# GUARDS: `git commit && git checkout main` is routine. A compile that finishes after
# the checkout must not write into the other branch's working tree; the extraction it
# paid for is kept in the cache so the next compile costs nothing.
def test_nothing_is_written_when_head_moved_during_the_compile(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "one")
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    extractor = DictExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]})

    with pytest.raises(HeadMoved, match="HEAD moved"):
        run_compile(store, extractor, expect_head="0" * 40)
    assert not store.claims_path.exists()
    assert not (tmp_path / ".lore" / "knowledge" / "README.md").exists()
    assert store.load_extraction("ses_1") is not None

    head = current_head(tmp_path)
    assert head and len(head) == 40
    run_compile(store, extractor, expect_head=head)
    assert len(store.load_claims()) == 1
    assert current_head(tmp_path / "nowhere") is None


class _ActingExtractor:
    """Stands in for a model call during which git moves on: runs `act` once, then
    answers with `claims`."""

    def __init__(self, act, claims):
        self._act = act
        self._claims = claims

    def extract(self, events, session_id, known_topics=None):
        if self._act is not None:
            self._act()
            self._act = None
        return list(self._claims)


# GUARDS: a fixup commit, or the later commits of a cherry-pick, land while the model is
# working; their own hook compiles are skipped by the lock. The first compile is still
# for the same line of work with the same committed claims, so throwing it away would
# leave nothing landed until some later commit.
def test_a_commit_that_follows_the_compiled_one_on_the_same_branch_is_accepted(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "one")
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    compiled_for = current_head(tmp_path)

    def fixup():
        _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "fixup during the model call")

    extractor = _ActingExtractor(fixup, [_claim("dedupe on idempotency key", "ses_1")])
    run_compile(store, extractor, expect_head=compiled_for)
    assert current_head(tmp_path) != compiled_for  # the fixup did land first
    assert len(store.load_claims()) == 1
    assert (tmp_path / ".lore" / "knowledge" / "README.md").exists()


# GUARDS: following on the same branch is not enough on its own. A switch to a branch
# that does not descend from the compiled commit, or a descendant on which the committed
# claims file differs (a review edit landed meanwhile), means the claims this compile
# started from are not the ones it would write over.
def test_a_branch_switch_or_a_changed_claims_file_during_the_compile_is_refused(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "one")
    _git(tmp_path, "checkout", "-q", "-b", "other")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "other work")
    _git(tmp_path, "checkout", "-q", "-")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "two")
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    claims = [_claim("dedupe on idempotency key", "ses_1")]

    def switch():
        _git(tmp_path, "checkout", "-q", "other")

    compiled_for = current_head(tmp_path)
    with pytest.raises(HeadMoved, match="HEAD moved") as refused:
        run_compile(store, _ActingExtractor(switch, claims), expect_head=compiled_for)
    assert "claims file" not in str(refused.value)
    assert not store.claims_path.exists()

    _git(tmp_path, "checkout", "-q", "-")
    run_compile(store, DictExtractor({"ses_1": claims}), expect_head=current_head(tmp_path))
    _git(tmp_path, "add", ".lore/claims/claims.jsonl")
    _git(tmp_path, "commit", "-q", "-m", "commit the compiled claims")
    compiled_for = current_head(tmp_path)

    def review():
        reviewed = store.claims_path.read_text().replace('"status":"active"', '"status":"archived"')
        assert reviewed != store.claims_path.read_text()
        store.claims_path.write_text(reviewed)
        _git(tmp_path, "commit", "-q", "-am", "review: archive the claim")

    newer = [_claim("retry the webhook with backoff", "ses_1")]
    with pytest.raises(HeadMoved, match="committed claims file changed"):
        run_compile(store, _ActingExtractor(review, newer), rebuild=True, expect_head=compiled_for)
    assert all(c.status == "archived" for c in store.load_claims())  # the review stands
    assert "backoff" not in store.claims_path.read_text()


# GUARDS: "nothing tracked written" must hold for `.lore/.gitignore` too. A store from an
# older version has a shorter, committed ignore list; the session and cache writes made
# before the head check must not refresh it, or a compile that ends in HeadMoved has
# still edited a tracked file. The refresh lands with the claims, after the check.
def test_head_moved_leaves_an_older_tracked_gitignore_untouched(tmp_path):
    _git(tmp_path, "init", "-q")
    lore_dir = tmp_path / ".lore"
    lore_dir.mkdir()
    older = "sessions/\ncache/\nclaims/usage.jsonl\n"
    (lore_dir / ".gitignore").write_text(older)
    (lore_dir / "config.yaml").write_text("model:\n  provider: anthropic\n")
    _git(tmp_path, "add", ".lore")
    _git(tmp_path, "commit", "-q", "-m", "an older store")
    store = LoreStore(tmp_path)
    _signal_session(store, "ses_1", "use idempotency key")
    extractor = DictExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]})

    with pytest.raises(HeadMoved):
        run_compile(store, extractor, expect_head="0" * 40)
    assert (lore_dir / ".gitignore").read_text() == older
    porcelain = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert porcelain == "", porcelain  # nothing tracked modified, nothing untracked

    run_compile(store, extractor, expect_head=current_head(tmp_path))
    assert ".*.tmp" in (lore_dir / ".gitignore").read_text().splitlines()


# GUARDS: a compile replays every cached extraction onto the committed claims, so the
# documented way to remove a claim in review is to archive it on its line, not to delete
# the line. The committed line comes first when duplicates merge, so its status wins; the
# lifecycle leaves non-active claims alone; the book shows active claims only. The deleted
# line does come back, which is why the docs say so; tombstones would change that half.
def test_a_claim_archived_on_its_line_in_review_stays_archived_when_the_cache_replays(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    kept = _claim("dedupe on idempotency key", "ses_1")
    deleted = _claim("retry the webhook with backoff", "ses_1")
    archived = _claim("use the ledger table", "ses_1")
    run_compile(store, DictExtractor({"ses_1": [kept, deleted, archived]}))
    assert len(store.load_claims()) == 3

    reviewed = []
    for line in store.claims_path.read_text().splitlines():
        if deleted.id in line:
            continue
        if archived.id in line:
            line = line.replace('"status":"active"', '"status":"archived"')
        reviewed.append(line + "\n")
    store.claims_path.write_text("".join(reviewed))

    run_compile(store, DictExtractor({}))  # the cached extraction answers, not the model
    by_id = {c.id: c for c in store.load_claims()}
    assert by_id[archived.id].status == "archived"  # the review stands
    assert by_id[deleted.id].status == "active"  # the deleted line is back from the cache
    book = (tmp_path / ".lore" / "knowledge" / "README.md").read_text()
    assert "ledger table" not in book and "backoff" in book
    pruned = apply_lifecycle(
        store.load_claims(), now=datetime.now(timezone.utc), max_unused_age=timedelta(days=30)
    )
    assert {c.id: c.status for c in pruned}[archived.id] == "archived"


# GUARDS: a render reproduces the stored claims and nothing else — not a cached
# extraction `lore compile` has not committed yet, not a claim a teammate removed in
# review that this machine's gitignored cache still holds.
def test_render_uses_the_stored_claims_only(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    committed = [_claim(f"stored claim {i}", "ses_1") for i in range(4)]
    store.write_claims(committed)
    before = store.claims_path.read_bytes()
    _signal_session(store, "ses_2", "use idempotency key")
    store.save_extraction("ses_2", [_claim("cached but never compiled", "ses_2")])
    _signal_session(store, "ses_3", "never extracted at all")

    result = run_render(store)
    assert result.rendered and result.changed_lines == 0
    assert {c.statement for c in result.claims} == {c.statement for c in committed}
    assert store.claims_path.read_bytes() == before
    assert result.unextracted_sessions == 1  # ses_3; ses_2 has its cache entry
    book = (tmp_path / ".lore" / "knowledge" / "README.md").read_text()
    assert book.count("**[gotcha]** stored claim") == 4 and "never compiled" not in book

    again = run_render(store)  # byte-stable on repeat
    assert again.changed_lines == 0 and store.claims_path.read_bytes() == before

    run_compile(store, DictExtractor({}))  # compile is what brings the cached session in
    assert len(store.load_claims()) == 5


def test_render_creates_nothing_in_a_store_without_claims(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    result = run_render(store)
    assert not result.rendered and result.claims == []
    for path in (
        store.claims_path,
        store.conflicts_path,
        tmp_path / ".lore" / "knowledge" / "README.md",
    ):
        assert not path.exists()


# GUARDS: serving never takes the compile lock, so a `lore query` or MCP call answered
# while the model works bumps the usage sidecar in the middle of a compile. The compile
# persists from the snapshot it loaded at the start; writing that snapshot's usage back
# would erase the bump, and the lifecycle would later archive the claim as never served.
def test_a_query_served_during_the_compile_keeps_its_usage_bump(tmp_path):
    store = LoreStore(tmp_path)
    store.init()
    served = _claim("dedupe on idempotency key", "ses_0")
    store.write_claims([served])
    _signal_session(store, "ses_1", "use idempotency key")

    class QueryingExtractor:
        """Stands in for a model call during which a query is answered."""

        def extract(self, events, session_id, known_topics=None):
            hits = KnowledgeServer(store).query("idempotency key")
            assert [c.id for c in hits] == [served.id]
            return [_claim("retry the webhook with backoff", session_id)]

    run_compile(store, QueryingExtractor())

    by_id = {c.id: c for c in store.load_claims()}
    assert len(by_id) == 2
    assert by_id[served.id].usage.times_served == 1
    assert store.load_usage()[served.id].times_served == 1


# GUARDS: a lock call can fail because the filesystem cannot lock at all (ENOLCK on some
# network mounts). That is not another compile: mapping every OSError to
# CompileInProgress skipped every compile on such a mount forever, behind a line that
# blamed a compile that did not exist. Only a "held" errno means another compile.
def test_a_filesystem_without_lock_support_warns_once_and_compiles(
    tmp_path, monkeypatch, capsys
):
    store = LoreStore(tmp_path)
    store.init()
    _signal_session(store, "ses_1", "use idempotency key")
    extractor = DictExtractor({"ses_1": [_claim("dedupe on idempotency key", "ses_1")]})
    unlocked = []

    def no_lock_support(fd):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(run_module, "_lock_exclusive", no_lock_support)
    monkeypatch.setattr(run_module, "_unlock", lambda fd: unlocked.append(fd))
    monkeypatch.setattr(run_module, "_warned_unguarded", False)

    run_compile(store, extractor)
    run_compile(store, extractor)
    assert len(store.load_claims()) == 1
    assert unlocked == []  # nothing was locked, so nothing is unlocked
    err = capsys.readouterr().err
    assert err.count("run unguarded") == 1 and "No locks available" in err

    def held_elsewhere(fd):
        raise OSError(errno.EAGAIN, "Resource temporarily unavailable")

    monkeypatch.setattr(run_module, "_lock_exclusive", held_elsewhere)
    with pytest.raises(CompileInProgress, match="another compile is running"):
        run_compile(store, extractor)

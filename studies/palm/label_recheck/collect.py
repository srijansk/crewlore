"""Read-only evidence on whether each declined PR's change later landed in its repository.

For every declined pull request in the study sample it records, with every GitHub
response cached on disk:
  * the PR as GitHub reports it now (state, merged, base sha, head sha, linked text);
  * timeline cross-references (other issues/PRs that mention it) and the merge state
    of every referencing PR;
  * merged PRs in the same repository, created from 14 days before the PR to 180 days
    after it closed, whose titles share most content words with its title;
  * line landing: the share of the PR's new, non-trivial added lines (absent from the
    file at the PR's base) that are present in the same file on the default branch
    30 and 180 days after the PR closed.
Only GET requests are made. Raw file contents come from raw.githubusercontent.com.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from corpus import AIDEV, load_tables  # noqa: E402
from poisoning import sample_prs  # noqa: E402

OUT = AIDEV / "label_recheck"
CACHE = OUT / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

STOP = set(
    """a an and are as at be by do does for from how in into is it its of on or that the
their then this to was we what when where which who why will with add adds added fix fixes
fixed update updates updated use uses make makes support implement implements""".split()
)


def _key(*parts: str) -> Path:
    return CACHE / (hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:24] + ".json")


def gh(path: str, *, paginate: bool = False, accept: str | None = None):
    """GET through `gh api`, cached. Returns parsed JSON or {'__error__': msg}."""
    key = _key("gh", path, str(paginate), accept or "")
    if key.exists():
        return json.loads(key.read_text())
    cmd = ["gh", "api", "-X", "GET", path]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    if accept:
        cmd += ["-H", f"Accept: {accept}"]
    for attempt in range(4):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            out = proc.stdout.strip()
            data = json.loads(out) if out else None
            if paginate and isinstance(data, list) and all(isinstance(p, list) for p in data):
                data = [item for page in data for item in page]  # --slurp: one list per page
            key.write_text(json.dumps(data))
            return data
        err = proc.stderr.strip()
        if "rate limit" in err.lower() or "secondary" in err.lower():
            time.sleep(30 * (attempt + 1))
            continue
        data = {"__error__": err[:300]}
        key.write_text(json.dumps(data))
        return data
    return {"__error__": "rate limited"}


def raw(repo: str, sha: str, path: str) -> str | None:
    key = _key("raw", repo, sha, path)
    if key.exists():
        v = json.loads(key.read_text())
        return v
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{urllib.parse.quote(path)}"
    text = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = resp.read()
                text = body.decode("utf-8", errors="replace") if len(body) < 3_000_000 else None
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                text = None
                break
            time.sleep(5 * (attempt + 1))
        except Exception:  # noqa: BLE001
            time.sleep(5 * (attempt + 1))
    key.write_text(json.dumps(text))
    return text


def words(text: str) -> set[str]:
    return {
        w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOP
    }


def norm(line: str) -> str:
    return " ".join(line.strip().split())


def nontrivial(line: str) -> bool:
    s = norm(line)
    if len(s) < 12:
        return False
    return len(re.findall(r"[A-Za-z0-9_]{2,}", s)) >= 3


def added_lines(patch: str) -> list[str]:
    out = []
    for ln in (patch or "").splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            if nontrivial(ln[1:]):
                out.append(norm(ln[1:]))
    return out


def commit_at(repo: str, branch: str, when: datetime) -> str | None:
    iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = gh(f"repos/{repo}/commits?sha={urllib.parse.quote(branch)}&until={iso}&per_page=1")
    if isinstance(data, list) and data:
        return data[0]["sha"]
    return None


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def new_lines_by_file(repo: str, pr: dict, files: list[dict]) -> dict[str, list[str]]:
    """The PR's non-trivial added lines that were absent from the file at its base."""
    base_sha = pr["base"]["sha"]
    out: dict[str, list[str]] = {}
    for f in sorted(files, key=lambda f: -(f.get("additions") or 0))[:12]:
        path = f["filename"]
        lines = added_lines(f.get("patch") or "")
        if not lines:
            continue
        base_text = raw(repo, base_sha, path) if f.get("status") != "added" else ""
        base_set = {norm(x) for x in (base_text or "").splitlines()}
        new = [ln for ln in dict.fromkeys(lines) if ln not in base_set]
        if new:
            out[path] = new
    return out


def share_at(repo: str, sha: str, new: dict[str, list[str]]) -> dict:
    total = sum(len(v) for v in new.values())
    hit = 0
    per = {}
    for path, lines in new.items():
        text = raw(repo, sha, path)
        have = {norm(x) for x in (text or "").splitlines()}
        n = sum(1 for ln in lines if ln in have)
        per[path] = n
        hit += n
    return {
        "sha": sha,
        "present": hit,
        "of": total,
        "share": round(hit / total, 3) if total else None,
    }


def landing(
    repo: str, pr: dict, files: list[dict], closed: datetime, candidates: list[int]
) -> dict:
    new = new_lines_by_file(repo, pr, files)
    out: dict = {"new_lines": sum(len(v) for v in new.values()), "history": {}, "candidates": {}}
    if not new:
        return out
    for days in (30, 180):
        sha = commit_at(repo, pr["base"]["ref"], closed + timedelta(days=days))
        if sha:
            out["history"][f"{days}d"] = share_at(repo, sha, new)
    for number in candidates:
        cand = gh(f"repos/{repo}/pulls/{number}")
        if isinstance(cand, dict) and cand.get("merged") and cand.get("merge_commit_sha"):
            rec = share_at(repo, cand["merge_commit_sha"], new)
            rec.update(
                {
                    "title": cand.get("title"),
                    "user": (cand.get("user") or {}).get("login"),
                    "base": cand["base"]["ref"],
                    "merged_at": cand.get("merged_at"),
                }
            )
            out["candidates"][str(number)] = rec
    head = gh(f"repos/{repo}/commits?per_page=1")
    if isinstance(head, list) and head:
        out["today"] = share_at(repo, head[0]["sha"], new)
    return out


def similar_merged(
    repo: str, title: str, created: datetime, closed: datetime, number: int
) -> list[dict]:
    lo = (created - timedelta(days=14)).strftime("%Y-%m-%d")
    hi = (closed + timedelta(days=180)).strftime("%Y-%m-%d")
    tw = words(title)
    if not tw:
        return []
    terms = sorted(tw, key=len, reverse=True)[:4]
    q = f"repo:{repo} is:pr is:merged created:{lo}..{hi} " + " ".join(terms)
    data = gh("search/issues?q=" + urllib.parse.quote(q) + "&per_page=30")
    time.sleep(2.5)  # search API: 30 requests a minute
    out = []
    for item in (data or {}).get("items", []) if isinstance(data, dict) else []:
        if item.get("number") == number:
            continue
        ow = words(item.get("title", ""))
        jacc = len(tw & ow) / max(1, len(tw | ow))
        out.append(
            {
                "number": item["number"],
                "title": item["title"],
                "user": (item.get("user") or {}).get("login"),
                "created_at": item.get("created_at"),
                "jaccard": round(jacc, 2),
                "url": item.get("html_url"),
            }
        )
    out.sort(key=lambda x: -x["jaccard"])
    return out[:5]


def cross_refs(repo: str, number: int) -> list[dict]:
    data = gh(f"repos/{repo}/issues/{number}/timeline?per_page=100", paginate=True)
    out = []
    if not isinstance(data, list):
        return [{"__error__": str(data)[:200]}]
    for ev in data:
        kind = ev.get("event")
        if kind == "cross-referenced":
            src = (ev.get("source") or {}).get("issue") or {}
            is_pr = "pull_request" in src
            merged_at = ((src.get("pull_request") or {}).get("merged_at")) if is_pr else None
            out.append(
                {
                    "event": kind,
                    "number": src.get("number"),
                    "title": src.get("title"),
                    "repo": ((src.get("repository") or {}).get("full_name")),
                    "is_pr": is_pr,
                    "state": src.get("state"),
                    "merged_at": merged_at,
                    "user": (src.get("user") or {}).get("login"),
                    "url": src.get("html_url"),
                    "at": ev.get("created_at"),
                }
            )
        elif kind in ("referenced", "closed", "reopened", "merged") and ev.get("commit_id"):
            out.append(
                {
                    "event": kind,
                    "commit_id": ev.get("commit_id"),
                    "at": ev.get("created_at"),
                    "actor": (ev.get("actor") or {}).get("login"),
                }
            )
        elif kind in ("reopened",):
            out.append({"event": kind, "at": ev.get("created_at")})
    return out


SIGNAL = re.compile(
    r"in favou?r of|supersed|duplicate|already (?:fixed|done|merged|implemented|addressed)|"
    r"fixed in|done in|handled in|addressed in|merged in|replaced by|moved to|"
    r"we(?:'ll| will) (?:do|handle|fix) (?:it|this)|i(?:'ll| will) (?:do|handle|fix|take)|"
    r"took over|pushed a fix|opened #|see #",
    re.I,
)


def comment_refs(repo: str, number: int) -> dict:
    """PR numbers and closing phrases in the declined PR's own comments and reviews."""
    texts = []
    for path in (
        f"repos/{repo}/issues/{number}/comments?per_page=100",
        f"repos/{repo}/pulls/{number}/reviews?per_page=100",
    ):
        data = gh(path, paginate=True)
        if isinstance(data, list):
            for c in data:
                body = c.get("body") or ""
                login = (c.get("user") or {}).get("login") or ""
                if body.strip() and not login.endswith("[bot]"):
                    texts.append({"user": (c.get("user") or {}).get("login"), "body": body})
    nums, phrases, quotes = set(), set(), []
    for t in texts:
        for m in re.findall(r"(?<![\w/])#(\d{1,6})\b", t["body"]):
            if int(m) != number:
                nums.add(int(m))
        for m in re.findall(rf"github\.com/{re.escape(repo)}/(?:pull|issues)/(\d+)", t["body"]):
            if int(m) != number:
                nums.add(int(m))
        hits = SIGNAL.findall(t["body"])
        if hits:
            phrases.update(h.lower() for h in hits)
            quotes.append({"user": t["user"], "excerpt": " ".join(t["body"].split())[:300]})
    refs = []
    for n in sorted(nums)[:8]:
        it = gh(f"repos/{repo}/issues/{n}")
        if isinstance(it, dict) and "number" in it:
            pr = it.get("pull_request") or {}
            refs.append(
                {
                    "number": n,
                    "is_pr": bool(pr),
                    "merged_at": pr.get("merged_at"),
                    "state": it.get("state"),
                    "title": it.get("title"),
                    "user": (it.get("user") or {}).get("login"),
                }
            )
    return {
        "refs": refs,
        "phrases": sorted(phrases),
        "quotes": quotes[:4],
        "n_comments": len(texts),
    }


def one(row: dict) -> dict:
    repo, number = row["repo"], int(row["number"])
    rec = {
        "repo": repo,
        "number": number,
        "title": row["title"],
        "agent": row.get("agent"),
        "url": f"https://github.com/{repo}/pull/{number}",
    }
    pr = gh(f"repos/{repo}/pulls/{number}")
    if not isinstance(pr, dict) or "__error__" in pr:
        rec["error"] = (pr or {}).get("__error__", "unknown") if isinstance(pr, dict) else "unknown"
        return rec
    rec.update(
        {
            "state": pr.get("state"),
            "merged": pr.get("merged"),
            "closed_at": pr.get("closed_at"),
            "created_at": pr.get("created_at"),
            "base_ref": pr["base"]["ref"],
            "default_branch": pr["base"]["repo"].get("default_branch"),
            "closed_by_body_refs": re.findall(
                r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", (pr.get("body") or ""), re.I
            ),
        }
    )
    files = gh(f"repos/{repo}/pulls/{number}/files?per_page=100", paginate=True)
    files = files if isinstance(files, list) else []
    rec["files_changed"] = len(files)
    closed = parse_ts(pr["closed_at"]) if pr.get("closed_at") else datetime.now(timezone.utc)
    created = parse_ts(pr["created_at"])
    rec["cross_refs"] = cross_refs(repo, number)
    rec["comments"] = comment_refs(repo, number)
    rec["similar_merged"] = similar_merged(repo, row["title"], created, closed, number)
    candidates = [s["number"] for s in rec["similar_merged"] if s["jaccard"] >= 0.3][:3]
    candidates += [
        c["number"]
        for c in rec["cross_refs"]
        if c.get("is_pr")
        and c.get("merged_at")
        and c.get("repo") == repo
        and c["number"] not in candidates
    ]
    candidates += [
        c["number"]
        for c in rec["comments"]["refs"]
        if c.get("is_pr") and c.get("merged_at") and c["number"] not in candidates
    ]
    try:
        rec["landing"] = landing(repo, pr, files, closed, candidates)
    except Exception as exc:  # noqa: BLE001
        rec["landing"] = {"error": f"{type(exc).__name__}: {exc}"}
    return rec


def main() -> None:
    sample = sample_prs(load_tables(), 60, 20260818)
    rows = [
        {"repo": r.repo, "number": str(r.number), "title": r.title, "agent": r.agent}
        for r in sample[sample["arm"] == "rejected"].itertuples()
    ]
    out_path = OUT / "evidence.jsonl"
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, rows))
    with out_path.open("w") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")
    print(f"wrote {len(results)} records to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

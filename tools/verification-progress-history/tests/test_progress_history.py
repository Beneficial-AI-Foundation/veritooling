"""progress_history: pure helpers, sampling, and JSONL/CSV output.

Deterministic units only; the probe binaries are left to the run guide. One test
drives a throwaway git repo (skipped when git is absent).
"""

import os
import shutil
import subprocess
from datetime import datetime, timezone

import progress_history as ph
import pytest


def test_last_line():
    assert ph._last_line("a\n\nb\n") == "b"
    assert ph._last_line("  x  ") == "x"
    assert ph._last_line("") == ""


def test_repo_name():
    assert ph.repo_name("https://github.com/o/dalek-verus.git") == "dalek-verus"
    assert ph.repo_name("/home/me/curve25519-dalek-lean-verify/") == "curve25519-dalek-lean-verify"
    assert ph.repo_name("") == "repo"


def test_norm_url():
    assert ph._norm_url("https://github.com/A/B.git/") == "https://github.com/a/b"
    assert ph._norm_url(None) is None


def test_commits_match_prefix_either_way():
    assert ph.commits_match("abcdef0123456789", "abcdef0")
    assert ph.commits_match("abcdef0", "abcdef0123456789")
    assert not ph.commits_match("abcdef0", "999")
    assert not ph.commits_match("abcdef0", None)


def test_envelope_commit_and_tool():
    assert ph.envelope_commit({"source": {"commit": "x"}}) == "x"
    assert ph.envelope_commit({"inputs": [{"source": {"commit": "y"}}]}) == "y"
    assert ph.envelope_commit({}) is None
    assert ph.envelope_tool({"tool": {"name": "probe-aeneas", "version": "0.16.0"}}) == (
        "probe-aeneas",
        "0.16.0",
    )
    assert ph.envelope_tool({}) == ("", "")


def test_aeneas_crate_dir(tmp_path):
    (tmp_path / "aeneas-config.yml").write_text(
        'aeneas:\n  commit: "abc"\ncrate:\n  dir: "curve25519-dalek"\n  name: "cd"\n'
    )
    assert ph._aeneas_crate_dir(tmp_path) == "curve25519-dalek"
    assert ph._aeneas_crate_dir(tmp_path / "nope") == "."  # no config -> repo root


def test_default_anchor_day_is_wednesday():
    # Weekly meeting is Thursday; the grid snaps to the prior Wednesday.
    assert ph.parse_args(["some/repo"]).anchor_day == "wednesday"


def test_anchor_weekday_lands_on_or_after():
    friday = ph.WEEKDAYS.index("friday")
    wed = datetime(2026, 1, 7, 12, tzinfo=timezone.utc)  # Wednesday
    a = ph.anchor_weekday(wed, friday)
    assert a.weekday() == 4 and a.date().isoformat() == "2026-01-09"
    fri = datetime(2026, 1, 9, 1, tzinfo=timezone.utc)  # already Friday
    assert ph.anchor_weekday(fri, friday).date().isoformat() == "2026-01-09"


def test_bucket_samples_one_per_period_plus_head():
    friday = ph.WEEKDAYS.index("friday")
    commits = [
        ("a", datetime(2026, 1, 5, tzinfo=timezone.utc)),  # week 1
        ("b", datetime(2026, 1, 8, tzinfo=timezone.utc)),  # week 1 (later -> wins)
        ("c", datetime(2026, 1, 15, tzinfo=timezone.utc)),  # week 2
    ]
    weekly = ph.bucket_samples(commits, friday, 1)
    shas = [s for _, s, _ in weekly]
    assert shas == ["b", "c"]  # 'a' dropped (same week as 'b'), HEAD 'c' present


def _git(cwd, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def test_resolve_commits_orders_and_anchors(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git not available")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a").write_text("1")
    _git(tmp_path, "add", "a")
    _git(tmp_path, "commit", "-qm", "c1", date="2026-01-07T12:00:00+00:00")  # Wed
    (tmp_path / "a").write_text("2")
    _git(tmp_path, "add", "a")
    _git(tmp_path, "commit", "-qm", "c2", date="2026-01-15T12:00:00+00:00")  # Thu

    friday = ph.WEEKDAYS.index("friday")
    # pass newest-first to prove it re-sorts oldest -> newest
    samples = ph.resolve_commits(tmp_path, ["HEAD", "HEAD~1"], friday)
    dates = [sd for sd, _, _ in samples]
    assert dates == ["2026-01-09", "2026-01-16"]  # Friday on/after each commit
    assert all(len(sha) == 40 for _, sha, _ in samples)


def test_append_record_upserts_by_commit(tmp_path):
    jsonl, csv_path = tmp_path / "progress.jsonl", tmp_path / "progress.csv"
    base = {"commit_date": "2026-01-01", "sample_date": "2026-01-02"}
    ph.append_record(jsonl, csv_path, {"commit": "aaa", "status": "extract_failed", **base})
    ph.append_record(
        jsonl,
        csv_path,
        {"commit": "bbb", "status": "ok", "commit_date": "2026-02-01", "sample_date": "2026-02-02"},
    )
    ph.append_record(jsonl, csv_path, {"commit": "aaa", "status": "ok", **base})  # revise aaa

    recs = ph._read_jsonl(jsonl)
    assert len(recs) == 2  # upsert, not append
    all_shas, ok_shas = ph.load_recorded(jsonl)
    assert all_shas == {"aaa", "bbb"} and ok_shas == {"aaa", "bbb"}
    # CSV: header + 2 rows, sorted by commit_date (aaa before bbb)
    lines = csv_path.read_text().splitlines()
    assert len(lines) == 3
    assert "aaa" in lines[1] and "bbb" in lines[2]

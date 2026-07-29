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


def test_fail_on_error_defaults_off():
    # Off by default (unattended cron opts in); the flag turns it on.
    assert ph.parse_args(["some/repo"]).fail_on_error is False
    assert ph.parse_args(["some/repo", "--fail-on-error"]).fail_on_error is True


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


def test_detect_leanblueprint_from_verso_lakefile(tmp_path):
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.30.0")
    (tmp_path / "lakefile.toml").write_text('[[require]]\nname = "versoBlueprint"\n')
    assert ph.detect_pipeline(tmp_path) == "leanblueprint"


def test_detect_leanblueprint_from_docs_lakefile(tmp_path):
    # versoBlueprint may be declared in the docs/ subproject, not the root.
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.30.0")
    (tmp_path / "lakefile.toml").write_text("# plain lean project\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "lakefile.lean").write_text('require versoBlueprint from git "..."')
    assert ph.detect_pipeline(tmp_path) == "leanblueprint"


def test_detect_leanblueprint_from_massot_tree(tmp_path):
    (tmp_path / "lakefile.toml").write_text("# plain lean project\n")
    (tmp_path / "blueprint" / "src").mkdir(parents=True)
    (tmp_path / "blueprint" / "src" / "web.tex").write_text("\\documentclass{article}")
    assert ph.detect_pipeline(tmp_path) == "leanblueprint"


def test_plain_lean_project_is_not_leanblueprint(tmp_path):
    # No versoBlueprint / no Massot tree -> the generic `lean` bucket, not blueprint.
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.30.0")
    (tmp_path / "lakefile.toml").write_text('[[require]]\nname = "mathlib"\n')
    assert ph.detect_pipeline(tmp_path) == "lean"


def test_blueprint_fields_in_record_schema():
    # bp_* columns exist and blank_metrics initialises them blank (so a colour
    # pipeline leaves them empty, mirroring `translated`).
    assert "bp_thm_proved_confirmed" in ph.RECORD_FIELDS
    blanks = ph.blank_metrics()
    assert all(blanks[f] == "" for f in ph.BLUEPRINT_FIELDS)
    assert ph.BLUEPRINT_FIELDS == [f"bp_{k}" for k in ph.BLUEPRINT_METRIC_KEYS]


def test_lean_version_from_toolchain():
    assert ph._lean_version_from_toolchain("leanprover/lean4:v4.30.0") == "v4.30.0"
    assert ph._lean_version_from_toolchain("leanprover/lean4:v4.29.0-rc4") == "v4.29.0-rc4"
    assert ph._lean_version_from_toolchain("") is None
    assert ph._lean_version_from_toolchain(None) is None


def test_leanblueprint_setup_selects_matching_probe_lean(tmp_path):
    import types

    project = tmp_path / "proj"
    project.mkdir()
    (project / "lean-toolchain").write_text("leanprover/lean4:v4.30.0")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    target = bindir / "probe-lean-v4.30.0"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    managed = tmp_path / "managed"
    managed.mkdir()
    args = types.SimpleNamespace(probe_lean_dir=bindir)
    state = {"managed_bin": managed}

    assert ph.leanblueprint_setup(project, args, state) is None
    link = managed / "probe-lean"
    assert link.is_symlink() and link.resolve() == target.resolve()
    assert state["probe_lean_version"] == "v4.30.0"


def test_leanblueprint_setup_missing_version_reports(tmp_path):
    import types

    project = tmp_path / "proj"
    project.mkdir()
    (project / "lean-toolchain").write_text("leanprover/lean4:v4.99.0")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    args = types.SimpleNamespace(probe_lean_dir=bindir)

    reason = ph.leanblueprint_setup(project, args, {"managed_bin": managed})
    assert reason and "v4.99.0" in reason
    assert not (managed / "probe-lean").exists()


def test_dep_cache_key_depends_on_toolchain_and_manifest(tmp_path):
    (tmp_path / "lake-manifest.json").write_text('{"packages":[{"name":"VCVio","rev":"abc"}]}')
    k1 = ph._dep_cache_key(tmp_path, "leanprover/lean4:v4.30.0")
    k2 = ph._dep_cache_key(tmp_path, "leanprover/lean4:v4.29.0")  # different toolchain
    (tmp_path / "lake-manifest.json").write_text('{"packages":[{"name":"VCVio","rev":"def"}]}')
    k3 = ph._dep_cache_key(tmp_path, "leanprover/lean4:v4.30.0")  # different manifest
    assert k1 != k2 and k1 != k3 and k2 != k3
    assert k1.startswith("v4.30.0-")  # readable toolchain prefix


def test_dep_cache_save_and_restore_roundtrip(tmp_path):
    # A fake project with two built dep packages.
    project = tmp_path / "proj"
    for dep, name in (("VCVio", "Foo.olean"), ("mathlib", "Bar.olean")):
        b = project / ".lake" / "packages" / dep / ".lake" / "build" / "lib"
        b.mkdir(parents=True)
        (b / name).write_text(f"olean:{dep}")
    (project / "lake-manifest.json").write_text('{"packages":[]}')
    cache = tmp_path / "cache"
    key = ph._dep_cache_key(project, "leanprover/lean4:v4.30.0")

    ph.save_dep_cache(project, cache, key)
    assert (cache / key / "VCVio" / "build" / "lib" / "Foo.olean").is_file()

    # Wipe the project's dep builds, then restore from cache.
    shutil.rmtree(project / ".lake" / "packages" / "VCVio" / ".lake" / "build")
    shutil.rmtree(project / ".lake" / "packages" / "mathlib" / ".lake" / "build")
    assert ph.restore_dep_cache(project, cache, key) is True
    restored = project / ".lake" / "packages" / "VCVio" / ".lake" / "build" / "lib" / "Foo.olean"
    assert restored.is_file() and restored.read_text() == "olean:VCVio"


def test_dep_cache_restore_miss_and_save_idempotent(tmp_path):
    project = tmp_path / "proj"
    b = project / ".lake" / "packages" / "VCVio" / ".lake" / "build"
    b.mkdir(parents=True)
    (b / "x.olean").write_text("v")
    (project / "lake-manifest.json").write_text("{}")
    cache = tmp_path / "cache"
    key = "v4.30.0-deadbeef"
    assert ph.restore_dep_cache(project, cache, key) is False  # nothing cached yet
    ph.save_dep_cache(project, cache, key)
    marker = cache / key / "VCVio" / "build" / "x.olean"
    assert marker.is_file()
    before = marker.stat().st_mtime
    ph.save_dep_cache(project, cache, key)  # idempotent: no re-copy
    assert marker.stat().st_mtime == before


def test_leanblueprint_clear_render_cache(tmp_path):
    site = tmp_path / "_out" / "site" / "html-multi"
    site.mkdir(parents=True)
    (site / "blueprint-manifest.json").write_text("{}")
    docs_site = tmp_path / "docs" / "_out" / "site"
    docs_site.mkdir(parents=True)
    ph.leanblueprint_clear_render_cache(tmp_path)
    assert not (tmp_path / "_out" / "site").exists()
    assert not docs_site.exists()

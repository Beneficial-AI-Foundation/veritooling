"""Tests for persist_progress_jsonl mapping (no DB required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from persist_progress_jsonl import (
    atoms_categories_from_record,
    load_ok_rows,
    load_repo_map,
    plot_categories_from_record,
    record_to_row,
    resolve_repo_id,
    validate_atoms_categories,
    validate_plot_categories,
)
from plot_progress import load_records

DATA = Path(__file__).resolve().parent.parent / "data"

OK_RECORD = {
    "repo": "dalek-verus",
    "pipeline": "verus",
    "sample_date": "2025-08-15",
    "commit": "4734da5d83d3e3847d6d0bceba233796be4089e2",
    "commit_date": "2025-08-13T10:25:02+00:00",
    "status": "ok",
    "grey": 80,
    "white": 269,
    "red": 0,
    "yellow": 7,
    "light_green": 3,
    "dark_green": 13,
    "purple": 3,
    "exec_total": 375,
    "tracked": 295,
    "verified": 16,
    "verified_trusted": 19,
    "translated": 0,
}


def test_plot_categories_match_burnup_svg_fields():
    cats = plot_categories_from_record(OK_RECORD)
    assert cats == {
        "tracked": 295,
        "verified": 16,
        "verified_trusted": 19,
        "translated": 0,
        "in_progress": 7,
        "unspecified": 269,
        "failed": 0,
    }
    assert not validate_plot_categories(OK_RECORD, cats)


def test_record_to_row_maps_meaning_based_fields():
    row = record_to_row(OK_RECORD, repo_id=5280)
    assert row is not None
    assert row["repo_id"] == 5280
    assert row["tracked"] == 295
    assert row["verified"] == 16
    assert row["verified_trusted"] == 19
    assert row["translated"] == 0
    assert row["unspecified"] == 269
    assert row["in_progress"] == 7
    assert row["snapshot_date"] == "2025-08-15"
    assert row["commit"] == OK_RECORD["commit"]
    assert row["pipeline"] == "verus"
    assert "data" not in row
    assert "total_functions" not in row
    assert "not_started" not in row
    assert "spec_only" not in row

def test_record_to_row_skips_non_ok():
    bad = {**OK_RECORD, "status": "verify_error"}
    assert record_to_row(bad, 1) is None


def test_record_to_row_rejects_inconsistent_verified():
    bad = {**OK_RECORD, "verified": 99}
    with pytest.raises(ValueError, match="verified"):
        record_to_row(bad, 1)


def test_persisted_matches_burnup_series_for_all_committed_jsonl():
    paths = sorted(DATA.glob("*/progress.jsonl"))
    assert paths, "expected committed data/*/progress.jsonl"
    for path in paths:
        records = load_records(path)
        ok = [r for r in records if r.get("status") == "ok"]
        rows, skipped = load_ok_rows(path, repo_id=1)
        assert skipped == len(records) - len(ok)
        assert len(rows) == len(ok)
        for record, row in zip(ok, rows, strict=True):
            if record.get("pipeline") == "leanblueprint":
                # No colour fields to compare against; the blueprint mapping has
                # its own test below.
                assert row["tracked"] == atoms_categories_from_record(record)["tracked"]
                continue
            assert row["tracked"] == record["tracked"]
            assert row["verified"] == record["verified"]
            assert row["verified_trusted"] == record["verified_trusted"]
            assert row["translated"] == record["translated"]
            assert row["in_progress"] == record["yellow"]
            assert row["unspecified"] == record["white"]
            assert record["verified"] == record["light_green"] + record["dark_green"]
            assert record["verified_trusted"] == record["verified"] + record["purple"]
            assert record["tracked"] == (
                record["white"]
                + record["red"]
                + record["yellow"]
                + record["verified"]
                + record["purple"]
            )


def test_resolve_repo_id_from_map():
    repo_map = load_repo_map(Path(__file__).resolve().parent.parent / "repos.map.json")
    assert resolve_repo_id(repo_map, "curve25519-dalek-lean-verify", "prod", None) == 5232
    assert resolve_repo_id(repo_map, "SparsePostQuantumRatchet-verify", "dev", None) == 5608
    assert resolve_repo_id(repo_map, "secure-messaging", "dev", None) == 5753
    assert resolve_repo_id(repo_map, "anything", "prod", 42) == 42
    with pytest.raises(ValueError, match="not in repo map"):
        resolve_repo_id(repo_map, "no-such-project", "prod", None)


def test_resolve_repo_id_requires_the_requested_env():
    # Every project in the committed map currently has all three envs, so use a
    # synthetic entry rather than pinning the test to whichever one lacks it.
    partial = {"proj": {"repo_ids": {"dev": 1}}}
    assert resolve_repo_id(partial, "proj", "dev", None) == 1
    with pytest.raises(ValueError, match="no repo_id"):
        resolve_repo_id(partial, "proj", "prod", None)


LEANBLUEPRINT_RECORD = {
    "repo": "secure-messaging",
    "pipeline": "leanblueprint",
    "sample_date": "2026-07-22",
    "commit": "08176cf8b75283bd82cf162caae4dcbf1ea4974b",
    "commit_date": "2026-07-21T15:54:32+00:00",
    "status": "ok",
    "bp_def_total": 58,
    "bp_def_formalized": 28,
    "bp_def_verified": 27,
    "bp_def_trusted": 0,
    "bp_def_in_progress": 0,
    "bp_def_failed": 0,
    "bp_def_unrealized": 1,
    "bp_thm_total": 56,
    "bp_thm_formalized": 9,
    "bp_thm_verified": 9,
    "bp_thm_trusted": 0,
    "bp_thm_in_progress": 0,
    "bp_thm_failed": 0,
    "bp_thm_unrealized": 0,
}


def test_atoms_categories_match_combined_atoms_chart():
    """Values match the final sample of data/secure-messaging/burnup-combined.svg."""
    cats = atoms_categories_from_record(LEANBLUEPRINT_RECORD)
    assert cats == {
        "tracked": 114,
        "verified": 36,
        "verified_trusted": 36,
        "translated": 0,
        "in_progress": 0,
        "unspecified": 77,
        "failed": 0,
    }
    assert not validate_atoms_categories(LEANBLUEPRINT_RECORD, cats)


def test_leanblueprint_row_uses_atoms_mapping_not_colour_fields():
    row = record_to_row(LEANBLUEPRINT_RECORD, repo_id=5753)
    assert row is not None
    assert row["tracked"] == 114
    assert row["verified"] == 36
    assert row["unspecified"] == 77
    assert row["translated"] == 0
    assert row["pipeline"] == "leanblueprint"
    assert json.loads(row["raw_record"])["bp_def_total"] == 58


def test_atoms_rejects_history_without_per_node_columns():
    """Absent columns coerce to 0, which would persist a silently empty series."""
    old = {k: v for k, v in LEANBLUEPRINT_RECORD.items() if not k.startswith("bp_def_verified")}
    cats = atoms_categories_from_record({**old, "bp_def_verified": 0})
    violations = validate_atoms_categories(old, cats)
    assert violations and "missing per-node proof-status columns" in violations[0]

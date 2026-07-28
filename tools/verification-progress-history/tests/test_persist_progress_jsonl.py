"""Tests for persist_progress_jsonl mapping (no DB required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from persist_progress_jsonl import (
    load_ok_rows,
    load_repo_map,
    plot_categories_from_record,
    record_to_row,
    resolve_repo_id,
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
    assert resolve_repo_id(repo_map, "curve25519-dalek-lean-verify", "prod", None) == 5280
    assert resolve_repo_id(repo_map, "SparsePostQuantumRatchet-verify", "dev", None) == 5664
    assert resolve_repo_id(repo_map, "anything", "prod", 42) == 42
    with pytest.raises(ValueError, match="no repo_id"):
        resolve_repo_id(repo_map, "dalek-verus", "prod", None)

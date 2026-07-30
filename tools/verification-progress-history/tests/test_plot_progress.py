"""plot_progress: record loading, y-axis scaling, and curve rendering."""

import json
import shutil

import plot_progress as pp


def _ok(date, **over):
    rec = {
        "status": "ok",
        "sample_date": date,
        "repo": "demo",
        "tracked": 100,
        "verified": 40,
        "verified_trusted": 45,
        "translated": 0,
        "yellow": 30,
        "white": 25,
        "red": 0,
    }
    rec.update(over)
    return rec


def test_load_records_coerces_ints_and_blanks(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(
        json.dumps(
            {
                "status": "ok",
                "sample_date": "2026-01-02",
                "tracked": "100",
                "yellow": "30",
                "white": "",
            }
        )
        + "\n"
    )
    (rec,) = pp.load_records(p)
    assert rec["tracked"] == 100 and rec["yellow"] == 30
    assert rec["white"] == 0  # blank metric -> 0, not "" or None


def test_nice_ceiling():
    assert pp.nice_ceiling(0) == 10
    assert pp.nice_ceiling(45) == 50
    assert pp.nice_ceiling(200) == 200
    assert pp.nice_ceiling(284) == 300  # dalek-lean tracked -> 300 y-max


def test_burnup_curves_are_opt_in():
    ok = [_ok("2026-01-02"), _ok("2026-02-06", verified=60)]
    base = pp.burnup_svg(ok, "t", "s")
    assert "<svg" in base and "tracked (ceiling)" in base
    assert "in-progress" not in base and "unspecified" not in base

    both = pp.burnup_svg(ok, "t", "s", show_in_progress=True, show_unspecified=True)
    assert "in-progress (sorry/assume)" in both
    assert "unspecified (no spec)" in both


def test_translated_line_only_for_aeneas():
    assert "translated (Aeneas)" not in pp.burnup_svg([_ok("2026-01-02")], "t", "s")
    ok = [_ok("2026-01-02", translated=20)]
    assert "translated (Aeneas)" in pp.burnup_svg(ok, "t", "s")


def test_failed_line_auto_drawn_only_when_present():
    # No failures -> no red curve (no flag, no clutter).
    assert ">failed<" not in pp.burnup_svg([_ok("2026-01-02", red=0)], "t", "s")
    # Any red -> the failed curve appears automatically, like `translated`.
    ok = [_ok("2026-01-02", red=0), _ok("2026-02-06", red=3)]
    assert ">failed</text>" in pp.burnup_svg(ok, "t", "s")


def test_main_default_output_name(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ok("2026-01-02")) + "\n")
    assert pp.main([str(p)]) == 0
    # progress.jsonl -> burnup.svg (not progress-burnup.svg)
    assert (tmp_path / "burnup.svg").is_file()


def test_main_png_when_converter_available(tmp_path):
    if not any(shutil.which(c) for c in ("rsvg-convert", "inkscape", "convert")):
        import pytest

        pytest.skip("no SVG->PNG converter on PATH")
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ok("2026-01-02")) + "\n")
    assert pp.main([str(p), "--png"]) == 0
    assert (tmp_path / "burnup.png").is_file()


def _bp(date, **over):
    rec = {
        "status": "ok",
        "sample_date": date,
        "repo": "secure-messaging",
        "pipeline": "leanblueprint",
        "bp_def_total": 58,
        "bp_def_formalized": 29,
        "bp_thm_total": 56,
        "bp_thm_formalized": 9,
        "bp_thm_proved": 9,
        "bp_thm_proved_confirmed": 8,
    }
    rec.update(over)
    return rec


def test_blueprint_two_panels_and_legends():
    ok = [_bp("2026-06-17", bp_thm_formalized=4), _bp("2026-07-29")]
    svg = pp.blueprint_svg(ok, "secure-messaging", "sub")
    # Two stacked panels (nested svgs) + the outer wrapper.
    assert svg.count("<svg") == 3
    assert "definitions" in svg and "theorems" in svg
    # Blueprint terminology, not colour-pipeline terms.
    assert "formalized" in svg and ">proved</text>" in svg
    assert "probe-lean-confirmed" not in svg  # kept out of the chart; it's in the docs
    assert "tracked (ceiling)" not in svg


def test_blueprint_mode_autodetected_from_pipeline(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bp("2026-07-29")) + "\n")
    assert pp.main([str(p)]) == 0
    svg = (tmp_path / "burnup.svg").read_text()
    assert "— definitions" in svg and "— theorems" in svg


def test_load_records_coerces_blueprint_fields(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps({"status": "ok", "bp_def_total": "58", "bp_thm_proved": ""}) + "\n")
    (rec,) = pp.load_records(p)
    assert rec["bp_def_total"] == 58 and rec["bp_thm_proved"] == 0


def _ln(date, **over):
    rec = {
        "status": "ok",
        "sample_date": date,
        "repo": "KeyedVerificationAnonymousCredential-model",
        "pipeline": "lean",
        "lean_def_total": 137,
        "lean_def_sorry": 0,
        "lean_def_verified": 0,
        "lean_def_trans_verified": 137,
        "lean_def_trusted": 0,
        "lean_def_failed": 0,
        "lean_thm_total": 37,
        "lean_thm_sorry": 0,
        "lean_thm_verified": 0,
        "lean_thm_trans_verified": 37,
        "lean_thm_trusted": 0,
        "lean_thm_failed": 0,
    }
    rec.update(over)
    return rec


# --------------------------------------------------------------------------- #
# Combined (--combined) chart
# --------------------------------------------------------------------------- #
def _bpa(date, **over):
    """A leanblueprint record with the per-node proof-status columns populated."""
    rec = _bp(date)
    rec.update(
        {
            "bp_def_verified": 20,
            "bp_def_trusted": 0,
            "bp_def_in_progress": 0,
            "bp_def_failed": 0,
            "bp_def_unrealized": 1,
            "bp_thm_verified": 8,
            "bp_thm_trusted": 0,
            "bp_thm_in_progress": 1,
            "bp_thm_failed": 0,
            "bp_thm_unrealized": 0,
        }
    )
    rec.update(over)
    return rec


def test_lean_two_panels_and_legends():
    ok = [_ln("2026-05-01", lean_thm_sorry=5, lean_thm_trans_verified=32), _ln("2026-07-29")]
    svg = pp.lean_svg(ok, "KVAC", "sub")
    assert svg.count("<svg") == 3  # two nested panels + outer wrapper
    assert "definitions" in svg and "theorems" in svg
    assert "without sorry" in svg and "trust boundary" in svg
    # lean terms, not colour-pipeline / blueprint terms
    assert "tracked (ceiling)" not in svg and ">formalized</text>" not in svg


def test_lean_mode_autodetected_from_pipeline(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ln("2026-07-29")) + "\n")
    assert pp.main([str(p)]) == 0
    svg = (tmp_path / "burnup.svg").read_text()
    assert "— definitions" in svg and "— theorems" in svg


def test_load_records_coerces_lean_fields(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps({"status": "ok", "lean_thm_total": "37", "lean_thm_sorry": ""}) + "\n")
    (rec,) = pp.load_records(p)
    assert rec["lean_thm_total"] == 37 and rec["lean_thm_sorry"] == 0


def test_combined_single_panel_and_fc_aligned_legend():
    ok = [_bpa("2026-06-24", bp_thm_verified=4), _bpa("2026-07-22")]  # thm_in_progress=1
    svg, warns = pp.combined_svg(ok, "secure-messaging", "sub", show_unspecified=True)
    assert warns == []
    assert svg.count("<svg") == 1  # one panel, not two
    assert "— combined" in svg
    # Band names match the FC colour burn-up vocabulary.
    assert "tracked (ceiling)" in svg
    assert "verified + trusted" in svg
    assert "in-progress (sorry/assume)" in svg  # present -> drawn
    assert "unrealized (no bound status)" in svg  # _bpa has bp_def_unrealized=1
    assert "unspecified (no statement)" in svg
    # The unit stays explicit via the y-axis label (not the FC "atom count").
    assert "blueprint nodes" in svg


def test_combined_status_curves_only_when_present():
    # A fully clean history: no in-progress / failed / unrealized -> no curves.
    clean = [
        _bpa(
            "2026-07-22",
            bp_thm_in_progress=0,
            bp_def_failed=0,
            bp_thm_failed=0,
            bp_def_unrealized=0,
        )
    ]
    svg, _ = pp.combined_svg(clean, "t", "s")
    assert "in-progress (sorry/assume)" not in svg
    assert ">failed</text>" not in svg
    assert "unrealized" not in svg
    # A failure / an over-claim -> the curve appears automatically.
    svg2, _ = pp.combined_svg([_bpa("2026-07-22", bp_def_failed=2)], "t", "s")
    assert ">failed</text>" in svg2
    assert "unrealized (no bound status)" in svg2  # _bpa default bp_def_unrealized=1


def test_combined_nesting_violation_warns_and_stamps():
    # verified impossibly large -> verified+trusted exceeds tracked.
    ok = [_bpa("2026-07-22", bp_def_verified=200)]
    svg, warns = pp.combined_svg(ok, "t", "s")
    assert warns and "nesting violated" in warns[0]
    assert "⚠" in svg  # rendered honestly with a stamped warning, not clamped


def test_combined_wrong_pipeline_errors(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ok("2026-01-02")) + "\n")  # colour pipeline record
    assert pp.main([str(p), "--combined"]) == 2


def test_combined_refuses_history_missing_columns(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bp("2026-07-22")) + "\n")  # old leanblueprint row, no bp_*_verified
    assert pp.main([str(p), "--combined"]) == 2  # must not silently render zeros
    assert not (tmp_path / "burnup-combined.svg").exists()


def test_combined_output_filename_distinct(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bpa("2026-07-22")) + "\n")
    assert pp.main([str(p), "--combined"]) == 0
    assert (tmp_path / "burnup-combined.svg").is_file()
    assert not (tmp_path / "burnup.svg").exists()  # never overwrites the two-panel chart


def test_combined_strict_exits_nonzero_on_violation(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bpa("2026-07-22", bp_def_verified=200)) + "\n")
    assert pp.main([str(p), "--combined"]) == 0  # still renders (warning only)
    assert pp.main([str(p), "--combined", "--strict"]) == 3  # strict escalates to nonzero


# --------------------------------------------------------------------------- #
# Combined (--combined) chart, lean pipeline
# --------------------------------------------------------------------------- #
def test_lean_combined_single_panel_and_fc_aligned_legend():
    # A mix: some sorry (in-progress) and some trusted, so the FC bands separate.
    ok = [
        _ln("2026-05-20", lean_def_total=9, lean_def_trans_verified=9),
        _ln("2026-07-29", lean_thm_sorry=5, lean_thm_trans_verified=30, lean_thm_trusted=2),
    ]
    svg, warns = pp.lean_combined_svg(ok, "KVAC", "sub")
    assert warns == []
    assert svg.count("<svg") == 1  # one panel, not two
    assert "— combined" in svg
    # FC vocabulary, not the lean two-panel terms.
    assert "tracked (ceiling)" in svg
    assert "verified + trusted" in svg
    assert "without sorry" not in svg and "trust boundary" not in svg
    assert "in-progress (sorry/assume)" in svg  # 5 sorries -> curve drawn
    # Unit is a declaration, and there is no blueprint statement axis.
    assert "declarations" in svg
    assert "unspecified (no statement)" not in svg
    assert "unrealized" not in svg


def test_lean_combined_clean_history_has_no_status_curves():
    svg, _ = pp.lean_combined_svg([_ln("2026-07-29")], "KVAC", "s")  # 0 sorry/failed
    assert "in-progress (sorry/assume)" not in svg
    assert ">failed</text>" not in svg


def test_lean_combined_mode_via_main_and_distinct_filename(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ln("2026-07-29")) + "\n")
    assert pp.main([str(p), "--combined"]) == 0
    assert (tmp_path / "burnup-combined.svg").is_file()
    assert not (tmp_path / "burnup.svg").exists()  # never overwrites the two-panel chart


def test_lean_combined_refuses_history_missing_columns(tmp_path):
    p = tmp_path / "progress.jsonl"
    # A lean row predating the kind-split status columns (only totals present).
    p.write_text(json.dumps({"status": "ok", "pipeline": "lean", "sample_date": "x"}) + "\n")
    assert pp.main([str(p), "--combined"]) == 2  # must not silently render zeros
    assert not (tmp_path / "burnup-combined.svg").exists()

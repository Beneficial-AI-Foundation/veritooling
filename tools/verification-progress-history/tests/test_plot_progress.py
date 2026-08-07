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
        "purple": 5,
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


def test_burnup_draws_exactly_the_three_categories_by_default():
    ok = [_ok("2026-01-02"), _ok("2026-02-06", verified=60)]
    base = pp.burnup_svg(ok, "t", "s").svg
    assert "<svg" in base
    assert pp.LBL_TRACKED in base
    assert pp.LBL_IN_PROGRESS in base  # in-progress is a default now, not a flag
    assert pp.LBL_COMPLETED in base
    # Everything else is behind a flag, even though this record has the data.
    assert "unspecified" not in base
    assert ">failed</text>" not in base
    assert "trusted (axiom-backed)" not in base


def test_burnup_overlays_are_opt_in():
    ok = [_ok("2026-01-02", translated=20, red=3, purple=5)]
    every = pp.burnup_svg(
        ok,
        "t",
        "s",
        pp.Overlays(trusted=True, unspecified=True, failed=True, translated=True),
    ).svg
    assert "unspecified (no spec)" in every
    assert ">failed</text>" in every
    assert "translated (Aeneas)" in every
    # --trusted exposes the axiom-backed slice of `completed`; both are drawn.
    assert "trusted (axiom-backed)" in every and pp.LBL_COMPLETED in every


def test_withheld_overlay_with_data_is_reported_not_dropped():
    # A failing sample draws nothing by default (red lives in the gap), so the
    # count has to surface on stderr or it would be invisible.
    quiet = pp.burnup_svg([_ok("2026-01-02", red=0)], "t", "s")
    assert quiet.notes == []
    withheld = pp.burnup_svg([_ok("2026-01-02", red=3)], "t", "s")
    assert any("failed peaks at 3" in n and "--failed" in n for n in withheld.notes)
    # Ask for the curve and there is nothing left to report.
    assert pp.burnup_svg([_ok("2026-01-02", red=3)], "t", "s", pp.Overlays(failed=True)).notes == []


def test_ceiling_invariants_warn_and_stamp():
    ok = [_ok("2026-01-02", verified_trusted=200)]  # completed above tracked=100
    r = pp.burnup_svg(ok, "t", "s")
    assert r.warnings and "completed (200) exceeds tracked (100)" in r.warnings[0]
    assert "⚠" in r.svg  # rendered honestly with a stamped warning, not clamped
    assert pp.burnup_svg([_ok("2026-01-02", yellow=500)], "t", "s").warnings


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


def test_blueprint_split_two_panels_and_legends():
    ok = [_bp("2026-06-17", bp_thm_formalized=4), _bp("2026-07-29")]
    svg = pp.blueprint_svg(ok, "secure-messaging", "sub").svg
    # Two stacked panels (nested svgs) + the outer wrapper.
    assert svg.count("<svg") == 3
    assert "definitions" in svg and "theorems" in svg
    # Blueprint terminology, not the three-category vocabulary.
    assert "formalized" in svg and ">proved</text>" in svg
    assert "probe-lean-confirmed" not in svg  # kept out of the chart; it's in the docs
    assert pp.LBL_TRACKED not in svg and pp.LBL_COMPLETED not in svg


def test_blueprint_split_is_opt_in_and_writes_its_own_file(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bpa("2026-07-29")) + "\n")
    assert pp.main([str(p), "--split"]) == 0
    svg = (tmp_path / "burnup-split.svg").read_text()
    assert "— definitions" in svg and "— theorems" in svg
    assert not (tmp_path / "burnup.svg").exists()  # never overwrites the default chart


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


def test_lean_split_two_panels_and_legends():
    ok = [_ln("2026-05-01", lean_thm_sorry=5, lean_thm_trans_verified=32), _ln("2026-07-29")]
    svg = pp.lean_svg(ok, "KVAC", "sub").svg
    assert svg.count("<svg") == 3  # two nested panels + outer wrapper
    assert "definitions" in svg and "theorems" in svg
    assert "without sorry" in svg and "trust boundary" in svg
    # lean terms, not the three-category / blueprint vocabulary
    assert pp.LBL_TRACKED not in svg and ">formalized</text>" not in svg


def test_lean_split_failed_curve_only_when_present():
    # The split layout is the diagnostic view, so `failed` stays automatic there
    # rather than waiting for --failed.
    assert ">failed</text>" not in pp.lean_svg([_ln("2026-07-29")], "KVAC", "s").svg
    svg = pp.lean_svg([_ln("2026-07-29", lean_thm_failed=3)], "KVAC", "s").svg
    assert ">failed</text>" in svg


def test_lean_split_is_opt_in(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ln("2026-07-29")) + "\n")
    assert pp.main([str(p), "--split"]) == 0
    svg = (tmp_path / "burnup-split.svg").read_text()
    assert "— definitions" in svg and "— theorems" in svg


def test_load_records_coerces_lean_fields(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps({"status": "ok", "lean_thm_total": "37", "lean_thm_sorry": ""}) + "\n")
    (rec,) = pp.load_records(p)
    assert rec["lean_thm_total"] == 37 and rec["lean_thm_sorry"] == 0


# --------------------------------------------------------------------------- #
# Pooled chart (the default for leanblueprint and lean)
# --------------------------------------------------------------------------- #
def test_bp_pooled_is_one_panel_in_the_three_categories():
    ok = [_bpa("2026-06-24", bp_thm_verified=4), _bpa("2026-07-22")]  # thm_in_progress=1
    r = pp.bp_pooled_svg(ok, "secure-messaging", "sub")
    assert r.warnings == []
    assert r.svg.count("<svg") == 1  # one panel, not two
    assert "— combined" not in r.svg  # one plot per project; no suffix to disambiguate
    # Same three categories as the colour chart; only the unit differs.
    assert pp.LBL_TRACKED in r.svg
    assert pp.LBL_COMPLETED in r.svg
    assert pp.LBL_IN_PROGRESS in r.svg
    assert "blueprint nodes" in r.svg
    # The blueprint's own axes belong to --split, not here.
    assert ">formalized</text>" not in r.svg and ">proved</text>" not in r.svg


def test_bp_pooled_overlays_are_opt_in():
    ok = [_bpa("2026-07-22", bp_def_failed=2)]
    quiet = pp.bp_pooled_svg(ok, "t", "s")
    assert ">failed</text>" not in quiet.svg
    assert "unrealized" not in quiet.svg  # _bpa has bp_def_unrealized=1
    assert "unspecified" not in quiet.svg
    # Withheld but non-zero -> reported, so nothing is silently lost.
    assert any("failed" in n for n in quiet.notes)
    assert any("unrealized" in n for n in quiet.notes)

    every = pp.bp_pooled_svg(
        ok, "t", "s", pp.Overlays(failed=True, unrealized=True, unspecified=True, trusted=True)
    )
    assert ">failed</text>" in every.svg
    assert "unrealized (no bound status)" in every.svg
    assert "unspecified (no statement)" in every.svg
    assert "trusted (axiom-backed)" in every.svg
    assert every.notes == []


def test_bp_pooled_ceiling_violation_warns_and_stamps():
    ok = [_bpa("2026-07-22", bp_def_verified=200)]  # completed far above the node total
    r = pp.bp_pooled_svg(ok, "t", "s")
    assert r.warnings and "completed" in r.warnings[0] and "exceeds tracked" in r.warnings[0]
    assert "⚠" in r.svg  # rendered honestly with a stamped warning, not clamped


def test_split_wrong_pipeline_errors(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ok("2026-01-02")) + "\n")  # colour pipeline record
    assert pp.main([str(p), "--split"]) == 2


def test_bp_pooled_refuses_history_missing_columns(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bp("2026-07-22")) + "\n")  # old leanblueprint row, no bp_*_verified
    assert pp.main([str(p)]) == 2  # must not silently render zeros
    assert not (tmp_path / "burnup.svg").exists()
    # The two-axis columns it does have are enough for the split layout.
    assert pp.main([str(p), "--split"]) == 0
    assert (tmp_path / "burnup-split.svg").is_file()


def test_pooled_is_the_default_output(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bpa("2026-07-22")) + "\n")
    assert pp.main([str(p)]) == 0
    svg = (tmp_path / "burnup.svg").read_text()
    assert svg.count("<svg") == 1 and pp.LBL_COMPLETED in svg
    assert not (tmp_path / "burnup-combined.svg").exists()  # the old name is gone


def test_deprecated_flags_are_no_ops(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bpa("2026-07-22")) + "\n")
    assert pp.main([str(p), "--combined"]) == 0
    assert (tmp_path / "burnup.svg").is_file()  # not burnup-combined.svg
    q = tmp_path / "colour.jsonl"
    q.write_text(json.dumps(_ok("2026-01-02")) + "\n")
    assert pp.main([str(q), "--in-progress"]) == 0


def test_strict_exits_nonzero_on_violation(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_bpa("2026-07-22", bp_def_verified=200)) + "\n")
    assert pp.main([str(p)]) == 0  # still renders (warning only)
    assert pp.main([str(p), "--strict"]) == 3  # strict escalates to nonzero


def test_lean_pooled_is_one_panel_and_keeps_the_total_ceiling():
    # A mix: some sorry (in-progress) and some trusted, so the bands separate.
    ok = [
        _ln("2026-05-20", lean_def_total=9, lean_def_trans_verified=9),
        _ln("2026-07-29", lean_thm_sorry=5, lean_thm_trans_verified=30, lean_thm_trusted=2),
    ]
    r = pp.lean_pooled_svg(ok, "KVAC", "sub")
    assert r.warnings == []
    assert r.svg.count("<svg") == 1  # one panel, not two
    # probe-lean has no curated tracked set, so the ceiling stays "total".
    assert "tracked" not in r.svg
    assert "total (ceiling)" in r.svg
    assert pp.LBL_COMPLETED in r.svg and pp.LBL_IN_PROGRESS in r.svg
    assert "without sorry" not in r.svg and "trust boundary" not in r.svg
    # Unit is a declaration, and there is no blueprint statement axis.
    assert "declarations" in r.svg
    assert "unspecified" not in r.svg and "unrealized" not in r.svg


def test_overlays_not_applicable_to_a_pipeline_are_dropped(tmp_path, capsys):
    # Plain Lean has no statement axis, so nothing there is `unspecified`; the
    # flag must be refused rather than drawn as a flat zero line posing as data.
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ln("2026-07-29")) + "\n")
    assert pp.main([str(p), "--unspecified", "--unrealized"]) == 0
    assert "not applicable" in capsys.readouterr().err
    assert "unspecified" not in (tmp_path / "burnup.svg").read_text()


def test_lean_pooled_default_output_and_missing_columns(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(_ln("2026-07-29")) + "\n")
    assert pp.main([str(p)]) == 0
    assert (tmp_path / "burnup.svg").is_file()
    # A lean row predating the kind-split status columns (only totals present).
    q = tmp_path / "old.jsonl"
    q.write_text(json.dumps({"status": "ok", "pipeline": "lean", "sample_date": "x"}) + "\n")
    assert pp.main([str(q)]) == 2  # must not silently render zeros
    assert not (tmp_path / "old-burnup.svg").exists()

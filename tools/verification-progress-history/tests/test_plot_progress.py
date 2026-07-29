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

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

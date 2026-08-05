"""blueprint_dashboard: the static cross-project index page."""

import json

import blueprint_dashboard


def _write(tmp_path, name, thm_status):
    """A one-theorem extract whose single theorem has the given machine status."""
    env = {
        "schema": "probe-leanblueprint/extract",
        "schema-version": "3.0",
        "source": {"repo": f"https://github.com/x/{name}.git", "commit": "deadbeef1234"},
        "data": {
            "probe:T": {
                "blueprint-label": "T",
                "blueprint-kind": "theorem",
                "blueprint-statement-status": "formalized",
                "blueprint-proof-status": "fully-proved",
                "language": "lean",
                "code-path": "T.lean",
                "verification-status": thm_status,
            }
        },
    }
    p = tmp_path / f"{name}.extract.json"
    p.write_text(json.dumps(env), encoding="utf-8")
    return p


def test_dashboard_writes_index_and_dot(tmp_path):
    # No SVG (avoids a graphviz dependency in CI): DOT files instead.
    a = _write(tmp_path, "alpha", "verified")  # machine-verified
    b = _write(tmp_path, "beta", "trusted")  # claimed but not green
    out = tmp_path / "site"
    rc = blueprint_dashboard.build_dashboard([a, b], out, "Test", render_svg=False)
    assert rc == 0

    index = (out / "index.html").read_text(encoding="utf-8")
    assert "alpha" in index and "beta" in index
    assert (out / "alpha.dot").is_file()
    assert (out / "beta.dot").is_file()
    # alpha is machine-verified (100%), beta is not (0%): both distinct from the
    # 100% claimed fraction both share.
    assert "100%" in index  # claimed
    assert "0%" in index  # beta machine-verified

    # Each project also gets its own insights.html, linked from the table.
    assert 'href="alpha.insights.html"' in index
    assert 'href="beta.insights.html"' in index
    assert (out / "alpha.insights.html").is_file()
    assert "Actionable" in (out / "alpha.insights.html").read_text(encoding="utf-8")


def test_dashboard_project_name_from_repo(tmp_path):
    a = _write(tmp_path, "myproj", "verified")
    out = tmp_path / "site"
    blueprint_dashboard.build_dashboard([a], out, "T", render_svg=False)
    assert (out / "myproj.dot").is_file()

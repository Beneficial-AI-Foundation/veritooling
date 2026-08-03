"""blueprint_insights: the closure/ranking/entry-index report."""

import blueprint_insights
import bp_graph


def _env(items):
    return {
        "schema": "probe-leanblueprint/extract",
        "schema-version": "3.0",
        "source": {"repo": "https://github.com/x/y.git", "commit": "abc123def"},
        "data": items,
    }


def _bound(label, **kw):
    a = {
        "blueprint-label": label,
        "blueprint-kind": kw.get("kind", "theorem"),
        "blueprint-statement-status": kw.get("statement", "none"),
        "blueprint-proof-status": kw.get("proof", "none"),
        "language": "lean",
        "code-path": f"{label}.lean",
    }
    if "status" in kw:
        a["verification-status"] = kw["status"]
    if "title" in kw:
        a["blueprint-title"] = kw["title"]
    for k in ("stmt_uses", "proof_uses"):
        if k in kw:
            a["blueprint-statement-uses" if k == "stmt_uses" else "blueprint-proof-uses"] = kw[k]
    return a


def _graph(items):
    return bp_graph.build_graph(_env(items))


def test_report_has_closure_ready_and_ranking():
    g = _graph(
        {
            "probe:A": _bound(
                "A", proof="fully-proved", status="verified", proof_uses=["probe:B"]
            ),
            "probe:B": _bound("B", proof="fully-proved", status="verified"),
        }
    )
    report = blueprint_insights.build_report(g, top_n=5)
    assert report["closure"]["thm_total"] == 2
    assert report["closure"]["claimed"]["closed"] == 2
    assert len(report["entry_index"]) == 2
    # A proof-uses B -> B has proof_uses=1, downstream=1; nothing statement-uses anything.
    assert report["most_used_proofs"][0]["label"] == "B"
    assert report["most_used_proofs"][0]["downstream_unlocks"] == 1
    assert report["most_used_statements"] == []
    assert "missing_informal_coverage" not in report  # no warnings_by_label given


def test_report_includes_missing_informal_coverage_when_given():
    g = _graph({"probe:A": _bound("A")})
    report = blueprint_insights.build_report(
        g, warnings_by_label={"A": {"leanOnlyNoStatement": True}}
    )
    assert report["missing_informal_coverage"] == ["A"]


def test_table_format_runs_without_manifest():
    g = _graph({"probe:A": _bound("A", statement="ready")})
    report = blueprint_insights.build_report(g)
    table = blueprint_insights._format_table(report)
    assert "not checked (no --manifest given)" in table
    assert "Actionable" in table


def test_table_format_shows_cycle_warning():
    g = _graph(
        {
            "probe:A": _bound(
                "A", proof="fully-proved", status="verified", proof_uses=["probe:B"]
            ),
            "probe:B": _bound(
                "B", proof="fully-proved", status="verified", proof_uses=["probe:A"]
            ),
        }
    )
    report = blueprint_insights.build_report(g)
    table = blueprint_insights._format_table(report)
    assert "dependency cycle" in table


def test_main_json_output(tmp_path, capsys):
    import json

    env = _env({"probe:A": _bound("A", proof="fully-proved", status="verified")})
    p = tmp_path / "e.json"
    p.write_text(json.dumps(env), encoding="utf-8")

    rc = blueprint_insights.main([str(p)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["closure"]["thm_total"] == 1


def test_main_missing_file_errors(capsys):
    rc = blueprint_insights.main(["/no/such/file.json"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_html_report_is_well_formed_and_shows_key_sections():
    import html.parser

    g = _graph(
        {
            "probe:A": _bound(
                "A", proof="fully-proved", status="verified", proof_uses=["probe:B"]
            ),
            "probe:B": _bound(
                "B", proof="fully-proved", status="verified", proof_uses=["probe:A"]
            ),
        }
    )
    report = blueprint_insights.build_report(g, top_n=5)
    out = blueprint_insights._format_html(report, top_n=5)

    html.parser.HTMLParser().feed(out)  # raises on malformed markup
    assert "Actionable" in out
    assert "Most used in statements" in out
    assert "Most used in proofs" in out
    assert "dependency cycle" in out  # A<->B cycle warning banner
    assert "Entry index" in out


def test_main_html_output_writes_file(tmp_path, capsys):
    import json

    env = _env({"probe:A": _bound("A", proof="fully-proved", status="verified")})
    p = tmp_path / "e.json"
    p.write_text(json.dumps(env), encoding="utf-8")
    out = tmp_path / "report.html"

    rc = blueprint_insights.main([str(p), "--html", "-o", str(out)])
    assert rc == 0
    assert "Wrote" in capsys.readouterr().out
    assert "<html" in out.read_text(encoding="utf-8")

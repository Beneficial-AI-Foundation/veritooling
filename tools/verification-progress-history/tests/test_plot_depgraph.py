"""plot_depgraph: DOT emission from a blueprint graph model."""

import bp_graph
import plot_depgraph


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


def _dot(items, **kw):
    return plot_depgraph.to_dot(bp_graph.build_graph(_env(items)), **kw)


def test_dot_has_nodes_edges_and_styles():
    dot = _dot(
        {
            "probe:A": _bound(
                "A",
                statement="formalized",
                proof="fully-proved",
                status="verified",
                stmt_uses=["probe:B"],
                proof_uses=["probe:B"],
            ),
            "probe:B": _bound("B", statement="ready"),
        }
    )
    assert dot.startswith("digraph blueprint {")
    # machine-verified fill present; solid statement edge and dashed proof edge.
    assert "#1F8A65" in dot
    assert "[style=solid]" in dot
    assert "[style=dashed]" in dot


def test_dot_escapes_quotes_in_header_title():
    dot = _dot({"probe:A": _bound("A")}, title='t "x"')
    # No raw unescaped double quote inside the header label text.
    assert '\\"x\\"' in dot


def test_node_text_is_blueprint_label_not_the_document_number():
    # blueprint-title ("Theorem 13.4.7") is the document's auto-numbering, not a
    # name, and is not single-valued the way blueprint-label is (a node can bind
    # more than one Lean decl). Node boxes must show the label, de-guillemeted.
    dot = _dot({"probe:A": _bound("«aead_security_exp»", title="Definition 1.4")})
    assert "aead_security_exp" in dot
    assert "Definition 1.4" not in dot


def test_legend_shows_only_present_states():
    dot = _dot({"probe:A": _bound("A", statement="ready")})  # only "ready"
    assert "leg_ready" in dot
    assert "leg_machine_verified" not in dot
    assert "leg_mismatch" not in dot


def test_header_reports_claimed_and_machine_verified():
    dot = _dot(
        {
            "probe:T": _bound(
                "T", kind="theorem", statement="formalized", proof="fully-proved", status="trusted"
            ),
        }
    )
    # claimed 1/1 (100%), machine-verified 0/1 (0%) -- trusted is not green.
    assert "claimed proved 1/1" in dot
    assert "machine-verified 0/1" in dot

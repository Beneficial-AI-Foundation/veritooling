"""verso_manifest: reading per-node warnings out of a raw Verso manifest."""

import json

import verso_manifest


def _manifest(nodes):
    return {"graphs": [{"nodes": nodes, "edges": [], "groups": []}]}


def _node(label, **warnings):
    return {"label": label, "kind": "theorem", "warnings": warnings}


def test_load_warnings_single_file(tmp_path):
    m = _manifest([_node("A", leanOnlyNoStatement=True), _node("B", unknownRef=True)])
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), encoding="utf-8")

    w = verso_manifest.load_manifest_warnings([p])
    assert w["A"]["leanOnlyNoStatement"] is True
    assert w["B"]["unknownRef"] is True
    assert w["B"].get("leanOnlyNoStatement", False) is False


def test_missing_informal_coverage_filters_by_flag(tmp_path):
    m = _manifest(
        [
            _node("A", leanOnlyNoStatement=True),
            _node("B", leanOnlyNoStatement=False, unknownRef=True),
            _node("C"),
        ]
    )
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), encoding="utf-8")

    w = verso_manifest.load_manifest_warnings([p])
    assert verso_manifest.missing_informal_coverage(w) == ["A"]


def test_merge_across_chapter_files_ors_flags(tmp_path):
    # Same label appears in two chapter manifests; a True flag anywhere wins.
    m1 = _manifest([_node("shared", leanOnlyNoStatement=False)])
    m2 = _manifest([_node("shared", leanOnlyNoStatement=True)])
    p1, p2 = tmp_path / "ch1.json", tmp_path / "ch2.json"
    p1.write_text(json.dumps(m1), encoding="utf-8")
    p2.write_text(json.dumps(m2), encoding="utf-8")

    w = verso_manifest.load_manifest_warnings([p1, p2])
    assert w["shared"]["leanOnlyNoStatement"] is True


def test_nodes_without_label_are_skipped(tmp_path):
    m = _manifest([{"kind": "theorem", "warnings": {"leanOnlyNoStatement": True}}])
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    assert verso_manifest.load_manifest_warnings([p]) == {}


def test_graphs_as_dict_not_list(tmp_path):
    # Defensive: tolerate a manifest whose "graphs" is a single object, not a list.
    m = {"graphs": {"nodes": [_node("A", leanOnlyNoStatement=True)]}}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    w = verso_manifest.load_manifest_warnings([p])
    assert w["A"]["leanOnlyNoStatement"] is True

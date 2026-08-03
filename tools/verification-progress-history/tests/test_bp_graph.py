"""bp_graph: the blueprint dependency-graph model built from one extract."""

import gzip
import json

import blueprint_progress
import bp_graph


def _atom(
    label,
    *,
    kind="theorem",
    statement="none",
    proof="none",
    language="blueprint",
    shadow=False,
    status=None,
    code_path=None,
    hidden=False,
    ignored=False,
    artifact=False,
    decl_missing=False,
    missing_decls=False,
    mismatch=False,
    stmt_uses=None,
    proof_uses=None,
    title=None,
    chapter=None,
    group=None,
):
    a = {
        "blueprint-label": label,
        "blueprint-kind": kind,
        "blueprint-statement-status": statement,
        "blueprint-proof-status": proof,
        "language": language,
    }
    if shadow:
        a["blueprint-shadow"] = True
    if status is not None:
        a["verification-status"] = status
    if code_path is not None:
        a["code-path"] = code_path
    if hidden:
        a["is-hidden"] = True
    if ignored:
        a["is-ignored"] = True
    if artifact:
        a["is-extraction-artifact"] = True
    if decl_missing:
        a["blueprint-decl-missing"] = True
    if missing_decls:
        a["blueprint-missing-decls"] = ["Foo.bar"]
    if mismatch:
        a["blueprint-status-mismatch"] = "claims-proved-but-unverified"
    if stmt_uses:
        a["blueprint-statement-uses"] = stmt_uses
    if proof_uses:
        a["blueprint-proof-uses"] = proof_uses
    if title:
        a["blueprint-title"] = title
    if chapter:
        a["blueprint-chapter"] = chapter
    if group:
        a["blueprint-group"] = group
    return a


def _env(items):
    return {
        "schema": "probe-leanblueprint/extract",
        "schema-version": "3.0",
        "source": {"repo": "r", "commit": "abc123def456"},
        "data": items,
    }


def _bound(label, **kw):
    """A real Lean atom bound to a blueprint node (included by default)."""
    kw.setdefault("language", "lean")
    kw.setdefault("code_path", f"{label}.lean")
    return _atom(label, **kw)


# --- node grouping --------------------------------------------------------


def test_grouping_by_label_matches_oracle():
    # Two atoms share one label -> one node; a null-label atom is skipped.
    env = _env(
        {
            "probe:blueprint:A": _atom("A", statement="formalized", proof="fully-proved"),
            "probe:A.impl": _bound(
                "A", statement="formalized", proof="fully-proved", status="verified"
            ),
            "probe:B": _bound("B", statement="ready", proof="ready", status="unverified"),
            "probe:noise": _atom(None, language="lean", code_path="n.lean"),
        }
    )
    g = bp_graph.build_graph(env)
    assert set(g.nodes) == {"A", "B"}
    # Node count agrees with the tested counter (the oracle).
    assert (
        bp_graph.summary(g)["nodes_total"] == blueprint_progress.count_blueprint(env)["nodes_total"]
    )


def test_bound_is_language_or_shadow_not_codepath():
    env = _env(
        {
            "probe:blueprint:S": _atom("S", shadow=True),  # synthetic but shadow -> bound
            "probe:blueprint:P": _atom("P"),  # pure blueprint atom -> planned
        }
    )
    g = bp_graph.build_graph(env)
    assert g.nodes["S"].bound is True
    assert g.nodes["P"].bound is False


def test_rollup_excludes_hidden_ignored_stub():
    env = _env(
        {
            "probe:H": _bound("N", status="failed", hidden=True),
            "probe:I": _bound("N", status="failed", ignored=True),
            "probe:X": _bound("N", status="failed", artifact=True),
            "probe:S": _bound("N", status="verified", code_path=""),  # empty path = external stub
            "probe:R": _bound("N", status="verified"),
        }
    )
    g = bp_graph.build_graph(env)
    # Only the one included, real atom's status counts.
    assert g.nodes["N"].statuses == ["verified"]


# --- colour state precedence ----------------------------------------------


def _state(**kw):
    env = _env(
        {
            "probe:blueprint:N": _atom(
                "N", **{k: v for k, v in kw.items() if k in ("statement", "proof")}
            ),
            "probe:N": _bound("N", **kw),
        }
    )
    return bp_graph.node_state(bp_graph.build_graph(env).nodes["N"])


def test_state_machine_verified():
    assert (
        _state(statement="formalized", proof="fully-proved", status="verified")
        == "machine-verified"
    )
    assert (
        _state(statement="formalized", proof="fully-proved", status="transitively-verified")
        == "machine-verified"
    )


def test_state_trusted_dominates_green():
    assert _state(statement="formalized", proof="fully-proved", status="trusted") == "trusted"


def test_state_mismatch_field_and_computed():
    # Explicit 3.0 flag.
    assert (
        _state(statement="formalized", proof="fully-proved", status="verified", mismatch=True)
        == "mismatch"
    )
    # Computed: claimed proved but the machine says sorry/failed.
    assert _state(statement="formalized", proof="fully-proved", status="unverified") == "mismatch"
    assert _state(statement="formalized", proof="fully-proved", status="failed") == "mismatch"


def test_state_failed_when_not_claimed():
    assert _state(statement="formalized", proof="none", status="failed") == "failed"


def test_state_proved_claimed_without_machine_backing():
    # fully-proved claim, but the only atom is synthetic (no machine status).
    env = _env({"probe:blueprint:N": _atom("N", statement="formalized", proof="fully-proved")})
    assert bp_graph.node_state(bp_graph.build_graph(env).nodes["N"]) == "proved-claimed"


def test_state_statement_ready_notready():
    assert _state(statement="formalized", proof="none") == "statement-formalized"
    assert _state(statement="ready", proof="none") == "ready"
    assert _state(statement="blocked", proof="none") == "not-ready"


# --- edge resolution ------------------------------------------------------


def test_edges_classes_and_resolution():
    env = _env(
        {
            "probe:A": _bound("A", stmt_uses=["probe:B"], proof_uses=["probe:C"]),
            "probe:B": _bound("B"),
            "probe:C": _bound("C"),
        }
    )
    g = bp_graph.build_graph(env)
    assert bp_graph.Edge("A", "B", "statement") in g.edges
    assert bp_graph.Edge("A", "C", "proof") in g.edges
    assert sum(g.dropped.values()) == 0


def test_edges_drop_self_missing_unlabeled_and_dedupe():
    env = _env(
        {
            # Node A uses: two DIFFERENT keys of label B (both resolve to B -> one
            # duplicate edge), another atom of A itself (self), a ghost key
            # (missing), and an unlabeled real atom (upstream).
            "probe:A.1": _bound(
                "A", proof_uses=["probe:B.1", "probe:B.2", "probe:A.2", "probe:ghost", "probe:up"]
            ),
            "probe:A.2": _bound("A"),  # second atom of label A -> self-edge target
            "probe:B.1": _bound("B"),
            "probe:B.2": _bound("B"),  # second atom of label B -> duplicate A->B edge
            "probe:up": _atom(None, language="lean", code_path="up.lean"),  # no blueprint-label
        }
    )
    g = bp_graph.build_graph(env)
    assert g.edges == [bp_graph.Edge("A", "B", "proof")]
    assert g.dropped["duplicate"] == 1
    assert g.dropped["self-edge"] == 1
    assert g.dropped["missing-key"] == 1
    assert g.dropped["upstream-unlabeled"] == 1


# --- summary + IO ---------------------------------------------------------


def test_summary_fractions_distinguish_claimed_from_verified():
    env = _env(
        {
            # thm 1: claimed fully-proved AND machine-verified (kind theorem by default)
            "probe:T1": _bound(
                "T1", statement="formalized", proof="fully-proved", status="verified"
            ),
            # thm 2: claimed fully-proved but only trusted (not machine green)
            "probe:T2": _bound(
                "T2", statement="formalized", proof="fully-proved", status="trusted"
            ),
        }
    )
    s = bp_graph.summary(bp_graph.build_graph(env))
    assert s["thm_total"] == 2
    assert s["thm_claimed_proved"] == 2
    assert s["thm_machine_verified"] == 1
    assert s["claimed_fraction"] == 1.0
    assert s["machine_verified_fraction"] == 0.5


def test_build_graph_file_reads_gzip(tmp_path):
    env = _env(
        {"probe:A": _bound("A", statement="formalized", proof="fully-proved", status="verified")}
    )
    p = tmp_path / "e.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(env, f)
    g = bp_graph.build_graph_file(p)
    assert set(g.nodes) == {"A"}


# --- closure metrics -------------------------------------------------------


def test_claimed_bucket_reads_proof_status_directly():
    # A -> fully-proved (closed); B -> proved but not fully (incomplete-deps);
    # C -> none with a sorry atom (sorry); D -> none, nothing bound (no-proof).
    env = _env(
        {
            "probe:A": _bound("A", proof="fully-proved"),
            "probe:B": _bound("B", proof="proved"),
            "probe:C": _bound("C", proof="none", status="unverified"),
            "probe:D": _atom("D", proof="none"),  # planned-only, no real atom
        }
    )
    g = bp_graph.build_graph(env)
    cs = bp_graph.closure_summary(g)
    assert cs["thm_total"] == 4
    assert cs["claimed"] == {"closed": 1, "incomplete-deps": 1, "sorry": 1, "no-proof": 1}


def test_machine_closure_catches_axiom_reliance_blueprint_bookkeeping_misses():
    # Both T and U CLAIM fully-proved (blueprint's own bookkeeping says fully
    # closed) -- but U's actual Lean binding only checks out as "trusted"
    # (axiom-reliant), which the blueprint's own accounting never sees. Our
    # machine cross-check catches it: neither T nor U ends up machine-closed,
    # even though the claimed view reports both as done. This mirrors the real
    # gap found on carleson (154 claimed-closed vs 140 machine-closed).
    env = _env(
        {
            "probe:T": _bound("T", proof="fully-proved", status="verified", proof_uses=["probe:U"]),
            "probe:U": _bound("U", proof="fully-proved", status="trusted"),
        }
    )
    g = bp_graph.build_graph(env)
    cs = bp_graph.closure_summary(g)
    assert cs["claimed"] == {"closed": 2, "incomplete-deps": 0, "sorry": 0, "no-proof": 0}
    assert cs["machine"] == {"closed": 0, "incomplete-deps": 2, "sorry": 0, "no-proof": 0}


def test_machine_closure_blocked_by_unclosed_dependency():
    env = _env(
        {
            "probe:T": _bound("T", proof="fully-proved", status="verified", proof_uses=["probe:U"]),
            "probe:U": _bound("U", proof="none", status="unverified"),  # sorry
        }
    )
    g = bp_graph.build_graph(env)
    cs = bp_graph.closure_summary(g)
    assert cs["machine"]["sorry"] == 1  # U
    assert cs["machine"]["incomplete-deps"] == 1  # T: locally fine, U blocks it


def test_machine_bucket_trusted_is_incomplete_not_no_proof():
    env = _env({"probe:T": _bound("T", proof="fully-proved", status="trusted")})
    g = bp_graph.build_graph(env)
    cs = bp_graph.closure_summary(g)
    assert cs["machine"] == {"closed": 0, "incomplete-deps": 1, "sorry": 0, "no-proof": 0}


def test_closure_reports_cycles_and_treats_them_as_not_closed():
    env = _env(
        {
            "probe:A": _bound("A", proof="fully-proved", status="verified", proof_uses=["probe:B"]),
            "probe:B": _bound("B", proof="fully-proved", status="verified", proof_uses=["probe:A"]),
        }
    )
    g = bp_graph.build_graph(env)
    closed, cycles = bp_graph.closure(g, bp_graph.machine_ok)
    assert closed["A"] is False
    assert closed["B"] is False
    # At least the back-edge node is reported; not necessarily every cycle member.
    assert "A" in cycles


def test_downstream_counts_transitive():
    # C -> B -> A: A has 2 downstream (B, C); B has 1 (C); C has 0.
    env = _env(
        {
            "probe:C": _bound("C", proof_uses=["probe:B"]),
            "probe:B": _bound("B", proof_uses=["probe:A"]),
            "probe:A": _bound("A"),
        }
    )
    g = bp_graph.build_graph(env)
    counts = bp_graph.downstream_counts(g)
    assert counts == {"A": 2, "B": 1, "C": 0}


def test_downstream_counts_excludes_self_on_a_cycle():
    # A -> B -> C -> A: the walk from any node loops back to itself. Each
    # should count the other 2 nodes, never itself.
    env = _env(
        {
            "probe:A": _bound("A", stmt_uses=["probe:B"]),
            "probe:B": _bound("B", stmt_uses=["probe:C"]),
            "probe:C": _bound("C", stmt_uses=["probe:A"]),
        }
    )
    g = bp_graph.build_graph(env)
    counts = bp_graph.downstream_counts(g)
    assert counts == {"A": 2, "B": 2, "C": 2}


def test_in_degree_splits_by_edge_class():
    env = _env(
        {
            "probe:A": _bound("A", stmt_uses=["probe:C"], proof_uses=["probe:C"]),
            "probe:B": _bound("B", proof_uses=["probe:C"]),
            "probe:C": _bound("C"),
        }
    )
    g = bp_graph.build_graph(env)
    ind = bp_graph.in_degree(g)
    assert ind["C"] == {"statement": 1, "proof": 2}
    assert ind["A"] == {"statement": 0, "proof": 0}


def test_actionable_requires_deps_formalized():
    env = _env(
        {
            "probe:R1": _bound("R1", statement="ready", stmt_uses=["probe:Dep"]),
            # Gives R1 a downstream dependent, so this test isolates the
            # deps-formalized check from the separate downstream>0 requirement
            # (see test_actionable_requires_nonzero_downstream).
            "probe:R1Dependent": _bound("R1Dependent", statement="ready", stmt_uses=["probe:R1"]),
            "probe:R2": _bound("R2", statement="ready", stmt_uses=["probe:Blocked"]),
            "probe:Dep": _bound("Dep", statement="formalized"),
            # "Blocked" is itself ready with no deps of its own, and R2 depends
            # on it, so it's ALSO actionable in its own right -- it just isn't a
            # usable dependency for R2, which is why R2 doesn't qualify.
            "probe:Blocked": _bound("Blocked", statement="ready"),
        }
    )
    g = bp_graph.build_graph(env)
    assert set(bp_graph.actionable(g)) == {"R1", "Blocked"}
    assert "R2" not in bp_graph.actionable(g)


def test_actionable_requires_nonzero_downstream():
    # An isolated ready node with no dependents unlocks nothing, so it
    # shouldn't count as actionable even though nothing blocks it either.
    env = _env({"probe:Island": _bound("Island", statement="ready")})
    g = bp_graph.build_graph(env)
    assert bp_graph.actionable(g) == []


def test_actionable_ignores_proof_only_dependencies():
    # X's only outgoing edge is a proof-use to Y (not yet formalized); nothing
    # about X's statement depends on Y, so it shouldn't block X. Z gives X a
    # downstream dependent so the downstream>0 filter doesn't also exclude it.
    env = _env(
        {
            "probe:X": _bound("X", statement="ready", proof_uses=["probe:Y"]),
            "probe:Y": _bound("Y", statement="blocked"),
            "probe:Z": _bound("Z", statement="ready", stmt_uses=["probe:X"]),
        }
    )
    g = bp_graph.build_graph(env)
    assert "X" in bp_graph.actionable(g)

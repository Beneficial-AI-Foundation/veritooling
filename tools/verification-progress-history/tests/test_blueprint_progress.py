"""count_blueprint: the two-axis progress record from one extract envelope."""

import blueprint_progress


def _node(
    kind, statement, proof, *, bound=False, decl_missing=False, missing_decls=False, mismatch=False
):
    """One blueprint node as a single atom.

    Bound nodes carry a real (non-``blueprint``) Lean atom; planned/decl-missing
    nodes carry only the ``blueprint``-language node atom.
    """
    atom = {
        "blueprint-label": None,  # filled by _envelope with a unique label
        "blueprint-kind": kind,
        "blueprint-statement-status": statement,
        "blueprint-proof-status": proof,
        "language": "lean" if bound else "blueprint",
    }
    if decl_missing:
        atom["blueprint-decl-missing"] = True
    if missing_decls:
        atom["blueprint-missing-decls"] = ["Foo.bar"]
    if mismatch:
        atom["blueprint-status-mismatch"] = "proof over-claimed"
    return atom


def _envelope(atoms):
    for i, atom in enumerate(atoms):
        atom["blueprint-label"] = f"node_{i}"
    return {
        "schema": "probe-leanblueprint/extract",
        "data": {str(i): a for i, a in enumerate(atoms)},
    }


def test_two_axis_counts():
    env = _envelope(
        [
            _node("definition", "formalized", "fully-proved", bound=True),  # def formalized, bound
            _node("definition", "ready", "ready"),  # def, planned-only
            _node("definition", "formalized", "proved", bound=True),  # formalized but not fully
            _node("theorem", "formalized", "fully-proved", bound=True),  # thm proved + confirmed
            _node(
                "theorem", "formalized", "fully-proved", decl_missing=True
            ),  # not bound -> unconfirmed
            _node(
                "theorem", "formalized", "fully-proved", bound=True, mismatch=True
            ),  # unconfirmed
            _node("theorem", "blocked", "none"),  # thm, planned-only
        ]
    )
    m = blueprint_progress.count_blueprint(env)

    assert (m["nodes_total"], m["nodes_bound"], m["nodes_planned"], m["nodes_decl_missing"]) == (
        7,
        4,
        2,
        1,
    )
    assert (m["def_total"], m["def_formalized"]) == (3, 2)
    assert (m["thm_total"], m["thm_formalized"]) == (4, 3)
    # Blueprint claims 3 fully-proved theorems; only 1 is probe-lean-confirmed
    # (the other two are decl-missing / status-mismatch).
    assert m["thm_proved"] == 3
    assert m["thm_proved_confirmed"] == 1
    assert m["warnings"] == []


def test_partial_missing_not_probe_lean_confirmed():
    # A bound, fully-proved theorem with some decls missing (partial-missing) is
    # NOT probe-lean-confirmed: probe-lean-confirmed needs the whole binding present.
    env = _envelope(
        [_node("theorem", "formalized", "fully-proved", bound=True, missing_decls=True)]
    )
    m = blueprint_progress.count_blueprint(env)
    assert m["thm_proved"] == 1  # blueprint claims it fully-proved
    assert m["thm_proved_confirmed"] == 0  # but partial-missing -> not confirmed


def test_shadow_atom_counts_as_bound():
    # A shadow atom (language "blueprint" but blueprint-shadow) is a genuinely
    # bound node preserved synthetically; it must count as bound.
    atom = _node("theorem", "formalized", "fully-proved")
    atom["blueprint-shadow"] = True
    m = blueprint_progress.count_blueprint(_envelope([atom]))
    assert m["nodes_bound"] == 1
    assert m["thm_proved_confirmed"] == 1


def test_atoms_without_blueprint_label_are_ignored():
    env = {
        "schema": "probe-leanblueprint/extract",
        "data": {
            "0": {"language": "lean", "kind": "def"},  # a plain code atom, no blueprint node
            "1": {
                "blueprint-label": "n",
                "blueprint-kind": "theorem",
                "blueprint-statement-status": "formalized",
                "blueprint-proof-status": "none",
                "language": "lean",
            },
        },
    }
    m = blueprint_progress.count_blueprint(env)
    assert m["nodes_total"] == 1
    assert m["thm_formalized"] == 1


def test_unexpected_schema_warns():
    env = {"schema": "probe-lean/extract", "data": {}}
    m = blueprint_progress.count_blueprint(env)
    assert m["nodes_total"] == 0
    assert any("unexpected schema" in w for w in m["warnings"])


# --------------------------------------------------------------------------- #
# Proof-status rollup (the combined-atoms buckets): one node, atoms grouped by
# blueprint-label, proof status folded from the real bound atoms' machine status.
# --------------------------------------------------------------------------- #
def _bound(kind, statement, vstatus, *, label="n", hidden=False, code_path="X.lean"):
    """A real bound Lean atom carrying a probe-lean verification-status."""
    a = {
        "blueprint-label": label,
        "blueprint-kind": kind,
        "blueprint-statement-status": statement,
        "blueprint-proof-status": "fully-proved",
        "language": "lean",
        "code-path": code_path,
        "verification-status": vstatus,
    }
    if hidden:
        a["is-hidden"] = True
    return a


def _bp_env(atoms):
    """Envelope from atoms that already carry their own blueprint-label."""
    data = {str(i): a for i, a in enumerate(atoms)}
    return {"schema": "probe-leanblueprint/extract", "data": data}


def test_bucket_sorry_def_is_in_progress():
    env = _bp_env([_bound("definition", "formalized", "unverified")])
    m = blueprint_progress.count_blueprint(env)
    assert (m["def_in_progress"], m["def_verified"], m["def_unrealized"]) == (1, 0, 0)


def test_bucket_failed_node():
    env = _bp_env([_bound("theorem", "formalized", "failed")])
    m = blueprint_progress.count_blueprint(env)
    assert (m["thm_failed"], m["thm_verified"]) == (1, 0)


def test_bucket_trusted_dominates_green():
    # A clean node binding one trusted (axiom) atom + one transitively-verified
    # atom must count as verified+trusted, NOT strict verified.
    env = _bp_env(
        [
            _bound("theorem", "formalized", "trusted", label="t"),
            _bound("theorem", "formalized", "transitively-verified", label="t"),
        ]
    )
    m = blueprint_progress.count_blueprint(env)
    assert m["thm_total"] == 1  # one node, two atoms
    assert m["thm_trusted"] == 1
    assert m["thm_verified"] == 0  # trust reliance keeps it out of strict green
    assert m["thm_verified"] + m["thm_trusted"] == 1  # in the completion frontier


def test_bucket_local_verified_counts_as_green():
    env = _bp_env([_bound("definition", "formalized", "verified")])
    m = blueprint_progress.count_blueprint(env)
    assert m["def_verified"] == 1  # colors.py counts local `verified` as green


def test_bucket_worst_status_is_order_independent():
    # Mixed statuses under one label: unverified must dominate regardless of order.
    a = _bound("theorem", "formalized", "transitively-verified", label="m")
    b = _bound("theorem", "formalized", "unverified", label="m")
    forward = blueprint_progress.count_blueprint(_bp_env([a, b]))
    backward = blueprint_progress.count_blueprint(_bp_env([b, a]))
    assert forward["thm_in_progress"] == backward["thm_in_progress"] == 1
    assert forward["thm_verified"] == backward["thm_verified"] == 0


def test_bucket_formalized_but_unbound_is_unrealized():
    # A formalized over-claim (decl-missing, no bound atom) is `unrealized`,
    # not miscounted as unspecified or verified.
    node = _node("theorem", "formalized", "fully-proved", decl_missing=True)
    node["blueprint-label"] = "over"
    m = blueprint_progress.count_blueprint(_bp_env([node]))
    assert m["thm_unrealized"] == 1
    assert m["thm_verified"] + m["thm_in_progress"] + m["thm_failed"] == 0


def test_bucket_excluded_atom_does_not_sway_status():
    # A hidden bound atom must be ignored; with no other status the formalized
    # node falls to `unrealized`, never silently `verified`.
    m = blueprint_progress.count_blueprint(
        _bp_env([_bound("definition", "formalized", "transitively-verified", hidden=True)])
    )
    assert m["def_verified"] == 0
    assert m["def_unrealized"] == 1


def test_unknown_status_warns():
    m = blueprint_progress.count_blueprint(_bp_env([_bound("theorem", "formalized", "bogus")]))
    assert any("unrecognised verification-status" in w for w in m["warnings"])


def test_formalized_partition_identity():
    # verified + trusted + in_progress + failed + unrealized == formalized, per kind.
    env = _bp_env(
        [
            _bound("definition", "formalized", "transitively-verified", label="d1"),
            _bound("definition", "formalized", "trusted", label="d2"),
            _bound("definition", "ready", "verified", label="d3"),  # unspecified
            _bound("theorem", "formalized", "unverified", label="t1"),
            _bound("theorem", "formalized", "failed", label="t2"),
        ]
    )
    m = blueprint_progress.count_blueprint(env)
    buckets = ("verified", "trusted", "in_progress", "failed", "unrealized")
    for p in ("def", "thm"):
        parts = sum(m[f"{p}_{b}"] for b in buckets)
        assert parts == m[f"{p}_formalized"]

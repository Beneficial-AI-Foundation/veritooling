"""count_blueprint: the two-axis progress record from one extract envelope."""

import blueprint_progress


def _node(kind, statement, proof, *, bound=False, decl_missing=False, mismatch=False):
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
    # Blueprint claims 3 fully-proved theorems; only 1 is machine-confirmed
    # (the other two are decl-missing / status-mismatch).
    assert m["thm_proved"] == 3
    assert m["thm_proved_confirmed"] == 1
    assert m["warnings"] == []


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

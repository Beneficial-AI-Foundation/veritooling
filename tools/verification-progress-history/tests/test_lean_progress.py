"""count_lean: the kind-split progress record from one probe-lean extract."""

import lean_progress


def _atom(kind, status, *, code_path="Foo.lean", **extra):
    a = {"kind": kind, "verification-status": status, "language": "lean", "code-path": code_path}
    a.update(extra)
    return a


def _envelope(atoms):
    return {"schema": "probe-lean/extract", "data": {str(i): a for i, a in enumerate(atoms)}}


def test_kind_split_and_status_tally():
    env = _envelope(
        [
            _atom("def", "transitively-verified"),
            _atom("abbrev", "verified"),  # locally clean, contaminated
            _atom("structure", "unverified"),  # a def with sorry
            _atom("theorem", "transitively-verified"),
            _atom("theorem", "verified"),  # locally clean, contaminated
            _atom("theorem", "unverified"),  # sorry
            _atom("theorem", "failed"),  # elaboration error
            _atom("axiom", "trusted", **{"trusted-reason": "axiom"}),  # -> theorem bucket
        ]
    )
    m = lean_progress.count_lean(env)

    assert (m["def_total"], m["def_sorry"], m["def_verified"], m["def_trans_verified"]) == (
        3,
        1,
        1,
        1,
    )
    # axiom lands in the theorem bucket and counts as trusted
    assert m["thm_total"] == 5
    assert (m["thm_sorry"], m["thm_verified"], m["thm_trans_verified"], m["thm_trusted"]) == (
        1,
        1,
        1,
        1,
    )
    assert m["thm_failed"] == 1
    assert m["warnings"] == []


def test_frontiers_nest():
    # without-sorry (verified+trans+trusted) >= trust-boundary (trans+trusted).
    env = _envelope(
        [
            _atom("theorem", "verified"),
            _atom("theorem", "transitively-verified"),
            _atom("theorem", "trusted"),
            _atom("theorem", "unverified"),
        ]
    )
    m = lean_progress.count_lean(env)
    no_sorry = m["thm_verified"] + m["thm_trans_verified"] + m["thm_trusted"]
    trust = m["thm_trans_verified"] + m["thm_trusted"]
    assert m["thm_total"] >= no_sorry >= trust
    assert (no_sorry, trust) == (3, 2)  # the lone `verified` is the gap


def test_excluded_atoms_are_dropped():
    env = _envelope(
        [
            _atom("def", "transitively-verified", code_path=""),  # external-crate stub
            _atom("def", "transitively-verified", **{"is-hidden": True}),
            _atom("theorem", "transitively-verified", **{"is-extraction-artifact": True}),
            _atom("def", "transitively-verified"),  # the only survivor
        ]
    )
    m = lean_progress.count_lean(env)
    assert m["def_total"] == 1 and m["thm_total"] == 0


def test_unexpected_schema_warns():
    m = lean_progress.count_lean({"schema": "probe-verus/extract", "data": {}})
    assert m["def_total"] == 0 and m["thm_total"] == 0
    assert any("unexpected schema" in w for w in m["warnings"])


def test_unknown_status_warns():
    # A status we don't bucket inflates total but no frontier -> must be surfaced.
    env = _envelope([_atom("def", "transitively-verified"), _atom("theorem", "quantum")])
    m = lean_progress.count_lean(env)
    assert m["def_total"] + m["thm_total"] == 2  # counted in total
    assert m["thm_verified"] == m["thm_trans_verified"] == 0  # but in no bucket
    assert any("unrecognised verification-status" in w and "quantum" in w for w in m["warnings"])


def test_missing_status_warns_skip_verify_case():
    # A --skip-verify extract emits atoms with no verification-status at all.
    env = _envelope([_atom("def", None), _atom("theorem", None)])
    m = lean_progress.count_lean(env)
    assert m["def_total"] == 1 and m["thm_total"] == 1
    assert any("no verification-status" in w for w in m["warnings"])

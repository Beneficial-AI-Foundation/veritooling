"""count_colors: the metric record derived from one extract envelope."""

import colors


def _exec(status, untracked=False, translated=False):
    return {
        "code-path": "src/x.rs",
        "language": "rust",
        "kind": "exec",
        "untracked": untracked,
        "verification-status": status,
        "translation-name": "Foo.bar" if translated else None,
    }


def _artifact(status, kind="proof"):
    return {"code-path": "X.lean", "language": "lean", "kind": kind, "verification-status": status}


def _envelope(atoms):
    return {"schema": "probe-aeneas/extract", "data": {str(i): a for i, a in enumerate(atoms)}}


def test_bar_and_dot_counts():
    env = _envelope(
        [
            _exec("verified", translated=True),
            _exec("transitively-verified", translated=True),
            _exec("unverified"),  # yellow == in-progress
            _exec(None),  # white == unspecified
            _exec("trusted"),  # purple
            _exec("verified", untracked=True),  # grey (out of scope)
            _artifact("verified"),  # dot_green
            _artifact("unverified"),  # dot_yellow
            {
                "code-path": "",
                "language": "rust",
                "kind": "exec",
                "verification-status": "verified",
            },  # excluded: external stub
            {
                "code-path": "src/y.rs",
                "language": "rust",
                "kind": "exec",
                "verification-status": "verified",
                "is-hidden": True,
            },  # excluded
        ]
    )
    m = colors.count_colors(env)

    assert m["pipeline"] == "aeneas"
    assert m["exec_total"] == 6  # excluded atoms are dropped before colouring
    assert (m["grey"], m["white"], m["yellow"], m["purple"]) == (1, 1, 1, 1)
    assert m["light_green"] == 1 and m["dark_green"] == 1
    assert m["tracked"] == 5  # exec_total - grey
    assert m["verified"] == 2  # light + dark green
    assert m["verified_trusted"] == 3  # + purple
    assert m["translated"] == 2
    assert (m["dot_green"], m["dot_yellow"], m["dot_red"]) == (1, 1, 0)
    assert m["art_total"] == 2
    assert m["warnings"] == []  # bar/dot covers reconcile


def test_translated_below_verified_warns():
    # A verified Aeneas atom without a translation-name is a consistency smell.
    env = _envelope([_exec("verified", translated=False)])
    m = colors.count_colors(env)
    assert m["verified"] == 1 and m["translated"] == 0
    assert any("translated" in w for w in m["warnings"])


def test_empty_envelope_is_all_zero():
    m = colors.count_colors({"schema": "probe-aeneas/extract", "data": {}})
    assert m["tracked"] == 0 and m["verified"] == 0 and m["warnings"] == []

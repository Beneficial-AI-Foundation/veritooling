"""Regression tests for specs-diff.py: status-transition classification and
git rename parsing."""

import json
from types import SimpleNamespace


def _atom(status, module="A", name=None, kind="theorem"):
    return {
        "kind": kind,
        "verification-status": status,
        "code-module": module,
        "display-name": name or f"{module}.decl",
    }


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps({"data": data}))
    return p


def test_probe_mode_classifies_schema2_transitions(specs_diff, tmp_path):
    """unverified->verified is newly_verified and verified->unverified is
    newly_broken, using the probe-lean Schema 2.0 vocabulary."""
    base = _write(
        tmp_path,
        "base.json",
        {
            "A.foo": _atom("unverified", name="foo"),
            "A.bar": _atom("verified", name="bar"),
        },
    )
    head = _write(
        tmp_path,
        "head.json",
        {
            "A.foo": _atom("verified", name="foo"),
            "A.bar": _atom("unverified", name="bar"),
            "A.baz": _atom("verified", name="baz"),
        },
    )
    changes = specs_diff.probe_mode(base, head)
    by_decl = {c["declaration"]: c["status"] for c in changes}
    assert by_decl["foo"] == "newly_verified"
    assert by_decl["bar"] == "newly_broken"
    assert by_decl["baz"] == "added"


def test_probe_mode_failed_counts_as_broken(specs_diff, tmp_path):
    base = _write(tmp_path, "base.json", {"A.foo": _atom("verified", name="foo")})
    head = _write(tmp_path, "head.json", {"A.foo": _atom("failed", name="foo")})
    changes = specs_diff.probe_mode(base, head)
    assert changes[0]["status"] == "newly_broken"


def test_git_diff_mode_reports_new_path_for_rename(specs_diff, monkeypatch):
    """A rename row (R100\\told\\tnew) must report the new path, not old\\tnew."""
    fake = SimpleNamespace(
        returncode=0,
        stdout="R100\told/Foo.lean\tnew/Foo.lean\nM\tSpecs/Bar.lean\n",
        stderr="",
    )
    monkeypatch.setattr(specs_diff.subprocess, "run", lambda *a, **k: fake)
    changes = specs_diff.git_diff_mode(["Specs"], "base")
    assert {"file": "new/Foo.lean", "status": "renamed"} in changes
    assert {"file": "Specs/Bar.lean", "status": "modified"} in changes

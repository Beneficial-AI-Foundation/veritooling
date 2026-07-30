#!/usr/bin/env python3
"""Count Lean blueprint progress on two axes from one extract envelope.

Sibling to ``colors.py``: where that derives the colour/verification metric set
for Verus/Aeneas extracts, this derives the *blueprint* progress metric set for a
``probe-leanblueprint/extract`` envelope. It is a stdlib-only port of the counts
in probe-leanblueprint's own ``scripts/blueprint_stats.py`` (``collect_nodes``),
so it doubles as an independent cross-check of that tool's summary sidecar.

Each blueprint node carries a two-axis status (see probe-leanblueprint's
docs/SCHEMA.md):

  statement  none -> blocked -> ready -> formalized   (is the statement in Lean?)
  proof      none -> ready   -> proved -> fully-proved (is the proof sorry-free?)

The burn-up uses axis-explicit terms, per kind (see the plan, "Terminology"):

  Formalized  statement-status == "formalized"      (both kinds)
  Proved      proof-status == "fully-proved"          (theorems)

"Proved" is reported twice: ``thm_proved`` is the blueprint's own claim, and
``thm_proved_confirmed`` is the **probe-lean-confirmed** count -- it additionally
requires probe-lean's own verification to back the claim (node bound, whole
binding present, no status mismatch), so a blueprint that over-claims doesn't
inflate it. For a code-derived Verso blueprint the two coincide; for a
``declared`` Massot blueprint they can diverge. (Matches probe-leanblueprint's
``theorems-fully-proved-probe-lean-confirmed``.)

Nodes split three ways (mirrors the sidecar ``totals``):
  bound         node bound to a real probe-lean decl (a.k.a. "with-lean-decl")
  planned       blueprint node with no decl at all (a pure stub)
  decl_missing  blueprint claims a decl probe-lean cannot find (an over-claim)

Usage:
    blueprint_progress.py <extract.json>          # print the metric record as JSON
    blueprint_progress.py <extract.json> --table  # human-readable table
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _iter_atoms(data) -> list:
    """``data`` is a map of probe-id -> atom (Schema 3.0); tolerate a list too."""
    if isinstance(data, dict):
        return list(data.values())
    if isinstance(data, list):
        return data
    return []


class _Node:
    """One blueprint node, assembled from all atoms sharing its blueprint-label."""

    __slots__ = (
        "kind",
        "statement",
        "proof",
        "bound",
        "decl_missing",
        "missing_decls",
        "mismatch",
        "statuses",
    )

    def __init__(self):
        self.kind = "theorem"
        self.statement = "none"
        self.proof = "none"
        self.bound = False
        self.decl_missing = False
        self.missing_decls = False  # partial-missing: bound but some decls absent
        self.mismatch = False
        # probe-lean `verification-status` values from this node's real bound
        # atoms (excludes synthetic `blueprint` atoms, which never carry one).
        # Folded to one node proof-status by `_proof_bucket`.
        self.statuses: list[str] = []


# probe-lean `verification-status` -> node proof-status, most-dominant first.
# Mirrors colors.py's status classes: `verified` and `transitively-verified` are
# both "green" (colors.py `verified = light_green + dark_green`); `trusted`
# (axiom / external) is the completion frontier's purple band and dominates green
# so any trust reliance in a node's own bindings keeps it out of strict
# `verified`; `unverified` (a sorry) and `failed` dominate everything.
_PROOF_RANK = {
    "failed": 4,
    "unverified": 3,
    "trusted": 2,
    "verified": 1,
    "transitively-verified": 1,
}
_RANK_BUCKET = {4: "failed", 3: "in_progress", 2: "trusted", 1: "verified"}


def _atom_included(atom: dict) -> bool:
    """Same exclusions as colors.py: drop external-crate stubs (empty code-path)
    and editorial/auto-generated atoms so they never sway a node's proof status."""
    return (
        atom.get("code-path", "") != ""
        and not atom.get("is-hidden", False)
        and not atom.get("is-ignored", False)
        and not atom.get("is-extraction-artifact", False)
    )


def _proof_bucket(statuses: list[str]) -> str | None:
    """Fold a node's bound-atom statuses to one proof bucket by precedence.

    Returns None when no atom carries a recognised machine status (an
    ``unrealized`` node -- formalized statement, nothing to verify against)."""
    ranks = [_PROOF_RANK[s] for s in statuses if s in _PROOF_RANK]
    if not ranks:
        return None
    return _RANK_BUCKET[max(ranks)]


def _kind_buckets(nodes: list[_Node]) -> dict:
    """Partition the *formalized* nodes of one kind by node proof-status.

    Every formalized node lands in exactly one bucket, so
    ``verified + trusted + in_progress + failed + unrealized`` == the kind's
    formalized count. Non-formalized nodes are ``unspecified`` and counted via
    ``total - formalized`` by the caller."""
    out = {"verified": 0, "trusted": 0, "in_progress": 0, "failed": 0, "unrealized": 0}
    for n in nodes:
        if n.statement != "formalized":
            continue
        bucket = _proof_bucket(n.statuses)
        out["unrealized" if bucket is None else bucket] += 1
    return out


def _collect_nodes(data) -> list[_Node]:
    """Group atoms by ``blueprint-label`` into one record per blueprint node.

    Mirrors probe-leanblueprint ``scripts/blueprint_stats.py``: a node is *bound*
    if any of its atoms is a real (non-``blueprint``-language) atom or a shadow
    atom (a genuinely-bound node whose Lean atom was claimed by a colliding
    node, kept synthetically to stay node-complete).
    """
    nodes: dict[str, _Node] = {}
    for atom in _iter_atoms(data):
        if not isinstance(atom, dict):
            continue
        label = atom.get("blueprint-label")
        if label is None:
            continue
        n = nodes.get(label)
        if n is None:
            n = _Node()
            nodes[label] = n
        n.kind = atom.get("blueprint-kind", n.kind)
        n.statement = atom.get("blueprint-statement-status", n.statement)
        n.proof = atom.get("blueprint-proof-status", n.proof)
        if atom.get("language") != "blueprint" or atom.get("blueprint-shadow"):
            n.bound = True
        # Collect the machine proof status from real bound atoms only. Synthetic
        # `blueprint` atoms (incl. shadows) never carry one; excluded atoms
        # (hidden / ignored / stub) must not sway the node's status.
        if atom.get("language") != "blueprint" and _atom_included(atom):
            vs = atom.get("verification-status")
            if vs is not None:
                n.statuses.append(vs)
        if atom.get("blueprint-decl-missing"):
            n.decl_missing = True
        if atom.get("blueprint-missing-decls"):
            n.missing_decls = True
        if atom.get("blueprint-status-mismatch"):
            n.mismatch = True
    return list(nodes.values())


def count_blueprint(envelope: dict) -> dict:
    """Compute the two-axis blueprint progress metric set for one extract envelope.

    Returns a flat dict with node buckets, per-kind totals, and the Formalized /
    Proved figures, plus any consistency ``warnings``.
    """
    schema = envelope.get("schema", "") or ""
    nodes = _collect_nodes(envelope.get("data"))

    defs = [n for n in nodes if n.kind == "definition"]
    thms = [n for n in nodes if n.kind != "definition"]

    nodes_total = len(nodes)
    nodes_bound = sum(1 for n in nodes if n.bound)
    nodes_decl_missing = sum(1 for n in nodes if n.decl_missing and not n.bound)
    nodes_planned = sum(1 for n in nodes if not n.bound and not n.decl_missing)

    def_formalized = sum(1 for n in defs if n.statement == "formalized")
    thm_formalized = sum(1 for n in thms if n.statement == "formalized")
    def_b = _kind_buckets(defs)
    thm_b = _kind_buckets(thms)
    thm_proved = sum(1 for n in thms if n.proof == "fully-proved")
    # probe-lean-confirmed: the blueprint claims fully-proved, the node's whole
    # binding is present (bound with no missing decls), and probe-lean did not
    # contradict it (no status mismatch). A "not refuted" bar, not "affirmatively
    # verified". Mirrors probe-leanblueprint's own summary headline.
    thm_proved_confirmed = sum(
        1
        for n in thms
        if n.proof == "fully-proved" and n.bound and not n.missing_decls and not n.mismatch
    )

    warnings: list[str] = []
    if schema and not schema.startswith("probe-leanblueprint"):
        warnings.append(f"unexpected schema {schema!r} (want probe-leanblueprint/extract)")
    if nodes_bound + nodes_planned + nodes_decl_missing != nodes_total:
        warnings.append(
            f"node buckets ({nodes_bound}+{nodes_planned}+{nodes_decl_missing}) "
            f"!= total ({nodes_total})"
        )
    if thm_proved_confirmed > thm_formalized:
        warnings.append(
            f"proved-confirmed ({thm_proved_confirmed}) > formalized ({thm_formalized}) "
            "-- a proved theorem is not statement-formalized"
        )

    # Unknown machine statuses would silently vanish from the buckets; surface them.
    known = set(_PROOF_RANK)
    unknown = {s for n in nodes for s in n.statuses if s not in known}
    if unknown:
        warnings.append(f"unrecognised verification-status values: {sorted(unknown)}")

    # Diagnostic (NOT a correctness gate): the status-based completion frontier
    # (probe-lean) and the blueprint's own claim-based proved-confirmed count
    # legitimately differ -- e.g. a locally-`verified` or `trusted` theorem is
    # proved-confirmed (a "not refuted" bar) yet sits in verified+trusted, while
    # a fully-proved claim with no machine status is confirmed but `unrealized`.
    # Kept separate from `warnings` so it never pollutes the recorded `reason`.
    diagnostics: list[str] = []
    thm_vt = thm_b["verified"] + thm_b["trusted"]
    if thm_vt != thm_proved_confirmed:
        diagnostics.append(
            f"status-based verified+trusted theorems ({thm_vt}) != blueprint "
            f"proved-confirmed ({thm_proved_confirmed}) -- machine status vs claim"
        )

    out = {
        "nodes_total": nodes_total,
        "nodes_bound": nodes_bound,
        "nodes_planned": nodes_planned,
        "nodes_decl_missing": nodes_decl_missing,
        "def_total": len(defs),
        "def_formalized": def_formalized,
        "thm_total": len(thms),
        "thm_formalized": thm_formalized,
        "thm_proved": thm_proved,
        "thm_proved_confirmed": thm_proved_confirmed,
    }
    # Per-kind proof-status buckets over the formalized nodes (probe-lean side).
    for kind, buckets in (("def", def_b), ("thm", thm_b)):
        for name, count in buckets.items():
            out[f"{kind}_{name}"] = count
    out["warnings"] = warnings
    out["diagnostics"] = diagnostics
    return out


def count_blueprint_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return count_blueprint(json.load(f))


def _proof_lines(m: dict, prefix: str) -> list[str]:
    """The probe-lean proof-status partition over one kind's formalized nodes."""
    unspecified = m[f"{prefix}_total"] - m[f"{prefix}_formalized"]
    return [
        f"  Proof status (of {m[f'{prefix}_formalized']} formalized, probe-lean):",
        f"    verified:         {m[f'{prefix}_verified']}   (green: verified + trans-verified)",
        f"    verified+trusted: {m[f'{prefix}_verified'] + m[f'{prefix}_trusted']}   "
        f"(+{m[f'{prefix}_trusted']} trusted: axiom/external)",
        f"    in-progress:      {m[f'{prefix}_in_progress']}   (sorry)",
        f"    failed:           {m[f'{prefix}_failed']}   (elaboration error)",
        f"    unrealized:       {m[f'{prefix}_unrealized']}   (formalized, no bound decl)",
        f"  Unspecified:  {unspecified}   (statement not formalized)",
    ]


def _format_table(m: dict) -> str:
    lines = [
        "Blueprint nodes",
        f"  Total:         {m['nodes_total']}",
        f"  Bound:         {m['nodes_bound']}   (with a probe-lean decl)",
        f"  Planned-only:  {m['nodes_planned']}   (pure stub, no decl)",
        f"  Decl-missing:  {m['nodes_decl_missing']}   (over-claim: decl not found)",
        "",
        "Definitions",
        f"  Total:      {m['def_total']}",
        f"  Formalized: {m['def_formalized']}",
        *_proof_lines(m, "def"),
        "",
        "Theorems",
        f"  Total:      {m['thm_total']}",
        f"  Formalized: {m['thm_formalized']}",
        f"  Proved:     {m['thm_proved']}   (blueprint claim)",
        f"  Proved (probe-lean-confirmed): {m['thm_proved_confirmed']}",
        *_proof_lines(m, "thm"),
    ]
    for w in m["warnings"]:
        lines.append(f"  WARNING: {w}")
    for d in m.get("diagnostics", []):
        lines.append(f"  [diag] {d}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count Lean blueprint progress (two axes).")
    parser.add_argument("input", type=Path, help="Path to a probe-leanblueprint/extract envelope.")
    parser.add_argument(
        "--table", action="store_true", help="Human-readable table instead of JSON."
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    metrics = count_blueprint_file(args.input)
    if args.table:
        print(_format_table(metrics))
    else:
        print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

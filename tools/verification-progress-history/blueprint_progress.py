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
``thm_proved_confirmed`` additionally requires probe-lean's own verification to
back it (node bound, no status mismatch) -- the honest headline, since a
blueprint may over-claim. For a code-derived Verso blueprint the two coincide;
for a ``declared`` Massot blueprint they can diverge.

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

    __slots__ = ("kind", "statement", "proof", "bound", "decl_missing", "mismatch")

    def __init__(self):
        self.kind = "theorem"
        self.statement = "none"
        self.proof = "none"
        self.bound = False
        self.decl_missing = False
        self.mismatch = False


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
        if atom.get("blueprint-decl-missing"):
            n.decl_missing = True
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
    thm_proved = sum(1 for n in thms if n.proof == "fully-proved")
    # Machine-confirmed: the blueprint claims fully-proved AND probe-lean backs it
    # (node bound, not contradicted). Mirrors probe-leanblueprint's own summary.
    thm_proved_confirmed = sum(
        1 for n in thms if n.proof == "fully-proved" and n.bound and not n.mismatch
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

    return {
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
        "warnings": warnings,
    }


def count_blueprint_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return count_blueprint(json.load(f))


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
        "",
        "Theorems",
        f"  Total:      {m['thm_total']}",
        f"  Formalized: {m['thm_formalized']}",
        f"  Proved:     {m['thm_proved']}   (blueprint claim)",
        f"  Proved (machine-confirmed): {m['thm_proved_confirmed']}",
    ]
    for w in m["warnings"]:
        lines.append(f"  WARNING: {w}")
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

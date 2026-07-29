#!/usr/bin/env python3
"""Count Lean progress per declaration kind from one probe-lean extract envelope.

Sibling to ``colors.py`` and ``blueprint_progress.py``. Where ``colors.py``
derives the colour/verification metric set (aggregated across the whole project)
and ``blueprint_progress.py`` derives the *blueprint* two-axis set, this derives a
kind-split progress set for a plain ``probe-lean/extract`` envelope -- a Lean
project with **no blueprint** (or an uninformative one, like KVAC-model, whose
blueprint is informal previews only, so probe-leanblueprint binds 0 nodes).

Two buckets, by ``kind`` (see probe-lean's docs/SCHEMA.md):

  theorems      kind in {theorem, axiom}   (proof obligations + assumed props)
  definitions   every other structural kind (def, abbrev, inductive, instance,
                structure, projection, opaque, ...)

An ``axiom`` is an assumed proposition, so it lands in the theorems bucket; it is
always ``trusted`` (no proof), which the trust boundary below counts.

Per bucket we tally the ``verification-status`` states (probe-lean's own sorry
detection + transitive contamination pass):

  sorry           status "unverified"            -- own body contains ``sorry``
  verified        status "verified"              -- locally sorry-free, but a
                                                    transitive dep is unverified
  trans_verified  status "transitively-verified" -- clean all the way to the base
  trusted         status "trusted"               -- axiom / @[externally_verified]
                                                    / *External.lean (assumed)
  failed          status "failed"                -- elaboration error

The burn-up (plot_progress.py) draws three nested frontiers from these, per
bucket, mirroring the VeriLib "verified + trusted" completion frontier:

  total                                                        (growing ceiling)
   >= without sorry  = verified + trans_verified + trusted     (no local sorry)
       >= trust boundary = trans_verified + trusted            (sound modulo the
                                                                 axioms/trust base)

``trust boundary`` sits *below* ``without sorry`` on purpose: being sound modulo
the trust base (transitively clean) is a stronger claim than merely having no
local ``sorry``. The gap between them is the ``verified``-but-transitively-
contaminated set (locally clean, a ``sorry`` still lurking downstream). Unlike a
blueprint history there is no fixed upper bound: ``total`` is just the declaration
count at each commit, which grows as code is added.

Atoms filtered before counting (same exclusions as ``colors.py``): external-crate
stubs (``code-path == ""``) and editorial/auto-generated exclusions
(``is-hidden`` / ``is-ignored`` / ``is-extraction-artifact``).

Usage:
    lean_progress.py <extract.json>          # print the metric record as JSON
    lean_progress.py <extract.json> --table  # human-readable table
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Kinds that count as "theorems" (proof obligations and assumed propositions);
# every other structural kind is a "definition". See probe-lean docs/SCHEMA.md.
THEOREM_KINDS = frozenset({"theorem", "axiom"})


def _iter_atoms(data) -> list:
    """``data`` is a map of probe-id -> atom (Schema 3.0); tolerate a list too."""
    if isinstance(data, dict):
        return list(data.values())
    if isinstance(data, list):
        return data
    return []


def _tally(atoms: list) -> dict:
    """Tally the verification-status states for one bucket of atoms."""
    return {
        "total": len(atoms),
        "sorry": sum(1 for a in atoms if a.get("verification-status") == "unverified"),
        "verified": sum(1 for a in atoms if a.get("verification-status") == "verified"),
        "trans_verified": sum(
            1 for a in atoms if a.get("verification-status") == "transitively-verified"
        ),
        "trusted": sum(1 for a in atoms if a.get("verification-status") == "trusted"),
        "failed": sum(1 for a in atoms if a.get("verification-status") == "failed"),
    }


def count_lean(envelope: dict) -> dict:
    """Compute the kind-split Lean progress metric set for one extract envelope.

    Returns a flat dict with ``def_*`` and ``thm_*`` tallies plus any consistency
    ``warnings``. The plot derives the three nested frontiers from these.
    """
    schema = envelope.get("schema", "") or ""
    atoms = [
        a
        for a in _iter_atoms(envelope.get("data"))
        if isinstance(a, dict)
        and a.get("code-path", "") != ""
        and not a.get("is-hidden", False)
        and not a.get("is-ignored", False)
        and not a.get("is-extraction-artifact", False)
    ]

    thms = [a for a in atoms if a.get("kind") in THEOREM_KINDS]
    defs = [a for a in atoms if a.get("kind") not in THEOREM_KINDS]

    out: dict = {}
    for prefix, bucket in (("def_", defs), ("thm_", thms)):
        for k, v in _tally(bucket).items():
            out[prefix + k] = v

    warnings: list[str] = []
    if schema and not schema.startswith("probe-lean/"):
        warnings.append(f"unexpected schema {schema!r} (want probe-lean/extract)")
    out["warnings"] = warnings
    return out


def count_lean_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return count_lean(json.load(f))


def _no_sorry(m: dict, p: str) -> int:
    return m[p + "verified"] + m[p + "trans_verified"] + m[p + "trusted"]


def _trust_boundary(m: dict, p: str) -> int:
    return m[p + "trans_verified"] + m[p + "trusted"]


def _format_bucket(m: dict, title: str, p: str) -> list[str]:
    return [
        title,
        f"  Total:          {m[p + 'total']}",
        f"  Without sorry:  {_no_sorry(m, p)}   (verified + trans-verified + trusted)",
        f"  Trust boundary: {_trust_boundary(m, p)}   (trans-verified + trusted)",
        f"    sorry:          {m[p + 'sorry']}",
        f"    verified:       {m[p + 'verified']}   (locally clean, dep contaminated)",
        f"    trans-verified: {m[p + 'trans_verified']}",
        f"    trusted:        {m[p + 'trusted']}   (axiom / external)",
        f"    failed:         {m[p + 'failed']}",
    ]


def _format_table(m: dict) -> str:
    lines = _format_bucket(m, "Definitions", "def_")
    lines.append("")
    lines += _format_bucket(m, "Theorems", "thm_")
    for w in m["warnings"]:
        lines.append(f"  WARNING: {w}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count Lean progress per declaration kind.")
    parser.add_argument("input", type=Path, help="Path to a probe-lean/extract envelope.")
    parser.add_argument(
        "--table", action="store_true", help="Human-readable table instead of JSON."
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    metrics = count_lean_file(args.input)
    if args.table:
        print(_format_table(metrics))
    else:
        print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

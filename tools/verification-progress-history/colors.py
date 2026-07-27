#!/usr/bin/env python3
"""Count atoms per colour, split by the two visual channels of the scheme.

Python port of the reference ``count-colors.sh`` documented in the VeriLib
engineering docs ("Atom statuses and colours"). Works with probe-aeneas/extract,
probe-verus/extract, and probe-lean/extract JSON; auto-detects the pipeline from
the ``schema`` field.

Two channels (see the doc for the full definition):

  Colour BAR  -- Rust ``exec`` atoms (language "rust", kind "exec").
    Pure function of (untracked, verification-status):
      grey        untracked: true            (out of verification scope)
      white       no verification-status     (tracked, no spec yet)
      red         "failed"
      yellow      "unverified"               (sorry / assume)
      light_green "verified"
      dark_green  "transitively-verified"
      purple      "trusted"

  Colour DOT  -- verification artifacts: Verus spec/proof and every Lean atom.
    Pure function of verification-status:
      red    "failed"
      yellow "unverified"
      green  otherwise (accepted by the tool)

Excluded from both channels before any colouring: external-crate stubs
(code-path == "") and editorial/auto-generated exclusions (is-hidden /
is-ignored / is-extraction-artifact).

Usage:
    colors.py <extract.json>          # print the metric record as JSON
    colors.py <extract.json> --table  # human-readable table (parity with the .sh)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def pipeline_from_schema(schema: str) -> str:
    """Map the envelope ``schema`` field to a pipeline name."""
    if schema.startswith("probe-aeneas"):
        return "aeneas"
    if schema.startswith("probe-verus"):
        return "verus"
    if schema.startswith("probe-lean"):
        return "lean"
    return "unknown"


def _iter_atoms(data) -> list:
    """`data` is a map of probe-id -> atom (Schema 2.0); tolerate a list too."""
    if isinstance(data, dict):
        return list(data.values())
    if isinstance(data, list):
        return data
    return []


def count_colors(envelope: dict) -> dict:
    """Compute the full colour/progress metric set for one extract envelope.

    Returns a flat dict with the seven bar colours, the three dot colours, the
    totals, and the derived progress figures (tracked / verified /
    verified_trusted / translated), plus any consistency ``warnings``.
    """
    schema = envelope.get("schema", "") or ""
    pipeline = pipeline_from_schema(schema)

    atoms = [
        a
        for a in _iter_atoms(envelope.get("data"))
        if isinstance(a, dict)
        and a.get("code-path", "") != ""
        and not a.get("is-hidden", False)
        and not a.get("is-ignored", False)
        and not a.get("is-extraction-artifact", False)
    ]

    # --- Colour BAR: Rust exec atoms -----------------------------------------
    execs = [
        {
            "untracked": a.get("untracked", False) is True,
            "status": a.get("verification-status"),
            "translated": a.get("translation-name") is not None,
        }
        for a in atoms
        if a.get("language") == "rust" and a.get("kind") == "exec"
    ]
    active = [e for e in execs if not e["untracked"]]

    grey = sum(1 for e in execs if e["untracked"])
    white = sum(1 for e in active if e["status"] is None)
    red = sum(1 for e in active if e["status"] == "failed")
    yellow = sum(1 for e in active if e["status"] == "unverified")
    light_green = sum(1 for e in active if e["status"] == "verified")
    dark_green = sum(1 for e in active if e["status"] == "transitively-verified")
    purple = sum(1 for e in active if e["status"] == "trusted")
    exec_total = len(execs)

    # --- Colour DOT: verification artifacts ----------------------------------
    # Verus spec/proof and every Lean atom. Keyed on kind (spec/proof) or
    # language (lean), matching the reference script.
    arts = [
        a.get("verification-status")
        for a in atoms
        if a.get("kind") in ("spec", "proof") or a.get("language") == "lean"
    ]
    dot_red = sum(1 for s in arts if s == "failed")
    dot_yellow = sum(1 for s in arts if s == "unverified")
    dot_green = sum(1 for s in arts if s not in ("failed", "unverified"))
    art_total = len(arts)

    # --- Derived progress figures --------------------------------------------
    tracked = exec_total - grey
    verified = light_green + dark_green
    verified_trusted = verified + purple
    translated = sum(1 for e in active if e["translated"])

    bar_cover = grey + white + red + yellow + light_green + dark_green + purple
    dot_cover = dot_red + dot_yellow + dot_green
    warnings: list[str] = []
    if bar_cover != exec_total:
        warnings.append(f"bar colours ({bar_cover}) != exec total ({exec_total})")
    if dot_cover != art_total:
        warnings.append(f"dot colours ({dot_cover}) != artifact total ({art_total})")
    if pipeline == "aeneas" and translated < verified:
        warnings.append(
            f"translated ({translated}) < verified ({verified}) "
            "-- a verified Aeneas atom is missing translation-name"
        )

    return {
        "pipeline": pipeline,
        "grey": grey,
        "white": white,
        "red": red,
        "yellow": yellow,
        "light_green": light_green,
        "dark_green": dark_green,
        "purple": purple,
        "exec_total": exec_total,
        "dot_red": dot_red,
        "dot_yellow": dot_yellow,
        "dot_green": dot_green,
        "art_total": art_total,
        "tracked": tracked,
        "verified": verified,
        "verified_trusted": verified_trusted,
        "translated": translated,
        "warnings": warnings,
    }


def count_colors_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return count_colors(json.load(f))


def _format_table(m: dict) -> str:
    lines = [
        f"Pipeline: {m['pipeline']}",
        "",
        "Colour BAR -- Rust exec atoms (verification status)",
        "# | Color       | Count",
        "--|-------------|------",
        f"1 | Grey        | {m['grey']}",
        f"2 | White       | {m['white']}",
        f"3 | Red         | {m['red']}",
        f"4 | Yellow      | {m['yellow']}",
        f"5 | Light Green | {m['light_green']}",
        f"6 | Dark Green  | {m['dark_green']}",
        f"7 | Purple      | {m['purple']}",
        "--|-------------|------",
        f"  | Total       | {m['exec_total']}",
        "",
        "Progress",
        f"    unspecified (white):              {m['white']}",
        f"    failed      (red):                {m['red']}",
        f"    in-progress (yellow):             {m['yellow']}",
        f"    verified    (light + dark green): {m['verified']}",
        f"    trusted     (purple):             {m['purple']}",
        f"    tracked     (total - grey):       {m['tracked']}",
        f"    translated  (Aeneas only):        {m['translated']}",
        f"    verified + trusted   (frontier):  {m['verified_trusted']}",
        "",
        "Colour DOT -- verification artifacts (checking status)",
        f"    Red    | {m['dot_red']}",
        f"    Yellow | {m['dot_yellow']}",
        f"    Green  | {m['dot_green']}",
        f"    Total  | {m['art_total']}",
    ]
    for w in m["warnings"]:
        lines.append(f"  WARNING: {w}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count atoms per colour (bar + dot channels).")
    parser.add_argument("input", type=Path, help="Path to a probe extract JSON envelope.")
    parser.add_argument(
        "--table", action="store_true", help="Human-readable table instead of JSON."
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    metrics = count_colors_file(args.input)
    if args.table:
        print(_format_table(metrics))
    else:
        print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

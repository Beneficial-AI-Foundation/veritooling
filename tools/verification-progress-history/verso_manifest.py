#!/usr/bin/env python3
"""Read per-node ``warnings`` straight out of a raw Verso blueprint manifest.

``probe-leanblueprint`` reads ``blueprint-manifest.json`` (the file `lake exe
vbp build` produces) but drops its ``warnings`` object entirely -- no
``blueprint-*`` field in the extract carries it forward (checked against
probe-leanblueprint's full field list). That object is the only place a
"missing informal coverage" signal exists: ``leanOnlyNoStatement`` means a node
is bound to a real Lean declaration but has no informal (natural-language)
statement or proof written for it.

Large blueprints render per-chapter, producing one ``blueprint-manifest.json``
per chapter rather than one merged file; pass every chapter's manifest path and
this merges by label.

This is a raw-manifest reader, not an extract consumer -- it only works where a
current manifest file is on disk (`docs/_out/site/**/blueprint-manifest.json`
after a `lake exe vbp build`). If the manifest was built at a different commit
than the extract you're cross-referencing, the label sets can disagree; this
module does not check that -- the caller is responsible for keeping them
aligned.

Usage:
    verso_manifest.py <manifest.json...>             # JSON: label -> warnings
    verso_manifest.py <manifest.json...> --missing-informal   # just the flagged labels
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _iter_graphs(manifest: dict):
    graphs = manifest.get("graphs")
    if isinstance(graphs, list):
        yield from graphs
    elif isinstance(graphs, dict):
        yield graphs


def load_manifest_warnings(paths: list[Path]) -> dict[str, dict[str, bool]]:
    """Merge ``warnings`` by label across one or more raw manifest files.

    A label seen in multiple manifests (e.g. re-exported across chapters) has
    its warning flags OR'd together -- a warning is real if any copy raises it.
    """
    out: dict[str, dict[str, bool]] = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        for graph in _iter_graphs(manifest):
            for node in graph.get("nodes", []):
                label = node.get("label")
                if label is None:
                    continue
                warnings = node.get("warnings") or {}
                merged = out.setdefault(label, {})
                for k, v in warnings.items():
                    merged[k] = merged.get(k, False) or bool(v)
    return out


def missing_informal_coverage(warnings_by_label: dict[str, dict[str, bool]]) -> list[str]:
    """Labels flagged ``leanOnlyNoStatement``: bound to Lean, no informal writeup."""
    return sorted(label for label, w in warnings_by_label.items() if w.get("leanOnlyNoStatement"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read per-node warnings from raw Verso manifest(s).")
    p.add_argument("inputs", type=Path, nargs="+", help="blueprint-manifest.json file(s).")
    p.add_argument(
        "--missing-informal",
        action="store_true",
        help="Print only labels flagged leanOnlyNoStatement (missing informal coverage).",
    )
    args = p.parse_args(argv)

    missing = [str(i) for i in args.inputs if not i.is_file()]
    if missing:
        print(f"Error: file(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 1

    warnings_by_label = load_manifest_warnings(args.inputs)
    if args.missing_informal:
        for label in missing_informal_coverage(warnings_by_label):
            print(label)
    else:
        print(json.dumps(warnings_by_label, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

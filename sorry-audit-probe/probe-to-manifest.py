#!/usr/bin/env python3
"""Convert probe-lean extract JSON to sorry-manifest v1 format.

Usage:
    python3 probe-to-manifest.py <probe-json> [--output PATH]

Reads a probe-lean Schema 2.0 JSON envelope and writes a sorry-manifest.txt
containing one line per declaration whose verification-status indicates sorry
contamination.

Mapping:
    verification-status "not_verified" or "has_sorry" → direct
    verification-status "transitively_not_verified"   → transitive
    All other statuses are not sorry-tainted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SORRY_DIRECT_STATUSES = {"not_verified", "has_sorry"}
SORRY_TRANSITIVE_STATUSES = {"transitively_not_verified"}
DEFAULT_OUTPUT = "sorry-manifest.txt"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert probe-lean JSON to sorry-manifest v1."
    )
    parser.add_argument("probe_json", type=Path, help="Path to probe-lean extract JSON")
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT), help="Output manifest path")
    args = parser.parse_args()

    if not args.probe_json.exists():
        print(f"Error: probe JSON not found at '{args.probe_json}'", file=sys.stderr)
        sys.exit(2)

    with open(args.probe_json) as f:
        envelope = json.load(f)

    data = envelope.get("data", {})
    lines: list[str] = []

    for atom_key, atom in data.items():
        status = atom.get("verification-status", "")
        if status in SORRY_DIRECT_STATUSES:
            kind = "direct"
        elif status in SORRY_TRANSITIVE_STATUSES:
            kind = "transitive"
        else:
            continue

        module = atom.get("code-module", "(unknown)")
        name = atom.get("display-name", atom_key)
        if name.startswith("probe:"):
            name = name[len("probe:"):]
        lines.append(f"{module} {name} {kind}")

    lines.sort()
    content = "# sorry-manifest v1\n" + "\n".join(lines) + ("\n" if lines else "")
    args.output.write_text(content)

    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"sorry-count={len(lines)}\n")
            f.write(f"manifest-path={args.output}\n")

    print(f"Converted {len(lines)} sorry-tainted declarations to {args.output}")


if __name__ == "__main__":
    main()

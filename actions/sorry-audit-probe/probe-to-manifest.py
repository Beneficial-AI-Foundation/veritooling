#!/usr/bin/env python3
"""Convert probe-lean extract JSON to sorry-manifest v1 format.

Usage:
    python3 probe-to-manifest.py <probe-json> [--output PATH]

Reads a probe-lean Schema 2.0 JSON envelope and writes a sorry-manifest.txt
containing one line per declaration whose verification-status indicates a
sorry.

Schema 2.0 verification-status vocabulary (probe-lean's WebVerificationStatus):
    verified, transitively-verified, trusted  -> clean
    unverified                                 -> direct sorry (VerifyStatus.sorries)
    failed                                     -> proof error (cannot occur in a
                                                  passing `lake build`)

Mapping:
    verification-status "unverified" -> direct sorry
    All other statuses are not sorry-tainted.

Note: schema 2.0 has no "transitively unverified" status -- the enrichment
pass only *upgrades* clean atoms to "transitively-verified" and leaves tainted
ones at their base status, so a transitive column is not emitted.

Manifest line format (whitespace-separated):
    <module> <declaration> <kind> [<file>:<line>]
The optional 4th column carries the declaration's source location so downstream
steps can emit GitHub annotations (`::warning file=...,line=...::`).  Consumers
that only need module/name/kind ignore it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Direct sorry signal in probe-lean schema 2.0.
SORRY_DIRECT_STATUSES = {"unverified"}
# Full schema-2.0 status vocabulary, used to detect schema drift: if a manifest
# contains statuses outside this set we are almost certainly parsing a schema we
# do not understand, and silently emitting an empty manifest would hide sorries.
KNOWN_STATUSES = {
    "verified",
    "transitively-verified",
    "trusted",
    "unverified",
    "failed",
}
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
    seen_statuses: set[str] = set()

    for atom_key, atom in data.items():
        status = atom.get("verification-status", "")
        seen_statuses.add(status)
        if status not in SORRY_DIRECT_STATUSES:
            continue

        module = atom.get("code-module", "(unknown)")
        name = atom.get("display-name", atom_key)
        if name.startswith("probe:"):
            name = name[len("probe:"):]

        path = atom.get("code-path", "")
        code_text = atom.get("code-text") or {}
        line_no = code_text.get("lines-start")
        location = f"{path}:{line_no}" if path and line_no else ""

        entry = f"{module} {name} direct"
        if location:
            entry += f" {location}"
        lines.append(entry)

    # Schema-drift guard: an empty manifest is only trustworthy if we recognised
    # the statuses we saw.  An unknown vocabulary means probe-lean changed its
    # schema and this converter would otherwise report "0 sorries" for a project
    # that has them (the exact failure that motivated this guard).
    unknown = {s for s in seen_statuses if s and s not in KNOWN_STATUSES}
    if unknown:
        print(
            f"::error::probe-to-manifest: unrecognised verification-status "
            f"value(s) {sorted(unknown)} -- probe-lean schema may have changed; "
            f"refusing to emit a possibly-empty manifest.",
            file=sys.stderr,
        )
        sys.exit(3)

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

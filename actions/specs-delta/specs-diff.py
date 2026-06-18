#!/usr/bin/env python3
"""Detect spec changes between base and head.

Supports two modes:
  git-diff  -- file-level detection via git diff
  probe     -- declaration-level detection via probe-lean JSON diff

Usage:
    python3 specs-diff.py git-diff --specs-paths P1,P2 --base-ref REF [--output PATH]
    python3 specs-diff.py probe --base-json F --head-json F [--output PATH]

Output: a JSON file with the detected changes and a markdown section.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_OUTPUT = "specs-delta.json"
DEFAULT_MARKDOWN = ".specs-delta-section.md"


def git_diff_mode(specs_paths: list[str], base_ref: str) -> list[dict]:
    """Detect spec file changes via git diff --name-status."""
    cmd = ["git", "diff", "--name-status", base_ref, "--"]
    cmd.extend(specs_paths)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"::warning::git diff failed: {result.stderr.strip()}", file=sys.stderr)
        return []

    changes: list[dict] = []
    status_map = {"A": "added", "M": "modified", "D": "deleted"}

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        raw_status = parts[0].strip()
        filepath = parts[1].strip()

        if raw_status.startswith("R"):
            status = "renamed"
        else:
            status = status_map.get(raw_status, raw_status)

        changes.append({"file": filepath, "status": status})

    return changes


def probe_mode(base_json_path: Path, head_json_path: Path) -> list[dict]:
    """Detect spec changes by diffing probe-lean JSON outputs."""
    with open(base_json_path) as f:
        base_data = json.load(f).get("data", {})
    with open(head_json_path) as f:
        head_data = json.load(f).get("data", {})

    def get_specs(data: dict) -> dict[str, dict]:
        """Extract declarations that are spec theorems or have specs."""
        specs: dict[str, dict] = {}
        for key, atom in data.items():
            atom_specs = atom.get("specs", [])
            status = atom.get("verification-status", "")
            kind = atom.get("kind", "")
            if kind in ("theorem", "lemma") or atom_specs:
                specs[key] = {
                    "specs": atom_specs,
                    "primary-spec": atom.get("primary-spec"),
                    "verification-status": status,
                    "kind": kind,
                    "module": atom.get("code-module", ""),
                    "display-name": atom.get("display-name", key),
                }
        return specs

    base_specs = get_specs(base_data)
    head_specs = get_specs(head_data)
    base_keys = set(base_specs)
    head_keys = set(head_specs)

    changes: list[dict] = []

    for key in sorted(head_keys - base_keys):
        atom = head_specs[key]
        changes.append({
            "declaration": atom["display-name"],
            "module": atom["module"],
            "status": "added",
            "verification-status": atom["verification-status"],
        })

    for key in sorted(base_keys - head_keys):
        atom = base_specs[key]
        changes.append({
            "declaration": atom["display-name"],
            "module": atom["module"],
            "status": "removed",
            "verification-status": atom["verification-status"],
        })

    for key in sorted(base_keys & head_keys):
        base_atom = base_specs[key]
        head_atom = head_specs[key]
        base_vs = base_atom["verification-status"]
        head_vs = head_atom["verification-status"]

        if base_vs != head_vs:
            if base_vs in ("not_verified", "has_sorry") and head_vs == "verified":
                change_status = "newly_verified"
            elif base_vs == "verified" and head_vs in ("not_verified", "has_sorry"):
                change_status = "newly_broken"
            else:
                change_status = "status_changed"

            changes.append({
                "declaration": head_atom["display-name"],
                "module": head_atom["module"],
                "status": change_status,
                "verification-status": head_vs,
                "previous-status": base_vs,
            })

    return changes


def format_markdown(changes: list[dict], mode: str) -> str:
    """Format spec changes as a markdown section."""
    sections: list[str] = ["#### Specs Delta", ""]

    if not changes:
        sections.append("No spec changes detected.")
        return "\n".join(sections)

    count = len(changes)
    s = "s" if count > 1 else ""
    sections.append(f"**{count}** spec change{s} detected ({mode} mode)")

    if mode == "git-diff":
        sections.append("")
        sections.append("| File | Status |")
        sections.append("|------|--------|")
        for change in changes:
            sections.append(f"| `{change['file']}` | {change['status']} |")
    else:
        sections.append("")
        sections.append("| Module | Declaration | Change | Status |")
        sections.append("|--------|-------------|--------|--------|")
        for change in changes:
            sections.append(
                f"| {change['module']} | `{change['declaration']}` "
                f"| {change['status']} | {change.get('verification-status', '')} |"
            )

    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect spec changes between base and head.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    git_parser = subparsers.add_parser("git-diff", help="File-level detection via git diff")
    git_parser.add_argument("--specs-paths", required=True, help="Comma-separated paths to specs directories")
    git_parser.add_argument("--base-ref", required=True, help="Base git ref for comparison")
    git_parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    git_parser.add_argument("--markdown-output", type=Path, default=Path(DEFAULT_MARKDOWN))

    probe_parser = subparsers.add_parser("probe", help="Declaration-level detection via probe-lean JSON")
    probe_parser.add_argument("--base-json", type=Path, required=True, help="Base probe-lean JSON")
    probe_parser.add_argument("--head-json", type=Path, required=True, help="Head probe-lean JSON")
    probe_parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    probe_parser.add_argument("--markdown-output", type=Path, default=Path(DEFAULT_MARKDOWN))

    args = parser.parse_args()

    if args.mode == "git-diff":
        paths = [p.strip() for p in args.specs_paths.split(",") if p.strip()]
        changes = git_diff_mode(paths, args.base_ref)
    else:
        if not args.base_json.exists():
            print(f"Error: base JSON not found at '{args.base_json}'", file=sys.stderr)
            sys.exit(2)
        if not args.head_json.exists():
            print(f"Error: head JSON not found at '{args.head_json}'", file=sys.stderr)
            sys.exit(2)
        changes = probe_mode(args.base_json, args.head_json)

    result = {"mode": args.mode, "changes": changes, "count": len(changes)}
    args.output.write_text(json.dumps(result, indent=2) + "\n")

    markdown = format_markdown(changes, args.mode)
    args.markdown_output.write_text(markdown + "\n")

    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"changed-count={len(changes)}\n")
            f.write(f"output-path={args.output}\n")

    print(f"Specs delta ({args.mode}): {len(changes)} changes")


if __name__ == "__main__":
    main()

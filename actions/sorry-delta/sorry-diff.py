#!/usr/bin/env python3
"""Compare two sorry manifests (base vs head) and produce a markdown delta
report suitable for a PR comment or GitHub Actions Job Summary.

Usage:
    python3 sorry-diff.py <base-manifest> <head-manifest> [--output PATH]
                          [--fail-on-new] [--summary] [--include-prefix PREFIXES]

When --include-prefix is given (comma- or whitespace-separated module
prefixes), the delta — counts, table, the `should-comment` signal, and
--fail-on-new — is restricted to declarations in those modules.  Use it to
report only hand-written code and ignore generated/extracted libraries.

Exit codes:
    0  success (or no new sorries)
    1  new sorries detected and --fail-on-new is set
    2  usage / file error
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

MANIFEST_VERSION_RE = re.compile(r"^#\s*sorry-manifest\s+v(\d+)\s*$")
SUPPORTED_VERSIONS = {1}
MAX_ROWS = 50
DEFAULT_OUTPUT = ".sorry-delta-section.md"


def read_manifest(path: Path) -> tuple[dict[str, str], int | None]:
    """Parse a versioned sorry manifest.

    Returns (declarations dict, version).  The dict maps declaration name
    (column 2) to the full line.  Version is None when the file is missing.
    """
    if not path.exists():
        return {}, None

    lines = path.read_text().splitlines()
    version: int | None = None
    result: dict[str, str] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = MANIFEST_VERSION_RE.match(stripped)
        if m:
            version = int(m.group(1))
            if version not in SUPPORTED_VERSIONS:
                print(
                    f"::warning::Unknown manifest version {version} "
                    f"in {path} (supported: {SUPPORTED_VERSIONS})",
                    file=sys.stderr,
                )
            continue
        if stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            result[parts[1]] = stripped

    return result, version


def parse_line(line: str) -> tuple[str, str, str]:
    parts = line.split()
    return (
        parts[0] if len(parts) > 0 else "",
        parts[1] if len(parts) > 1 else "",
        parts[2] if len(parts) > 2 else "",
    )


def parse_prefixes(raw: str) -> list[str]:
    """Split a comma- or whitespace-separated prefix list into clean tokens."""
    return [p for p in raw.replace(",", " ").split() if p]


def module_matches(module: str, prefixes: list[str]) -> bool:
    """True if `module` equals or descends from any of `prefixes`."""
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def filter_lines(lines: list[str], prefixes: list[str]) -> list[str]:
    """Keep only manifest lines whose module column matches a prefix."""
    if not prefixes:
        return lines
    return [l for l in lines if module_matches(parse_line(l)[0], prefixes)]


def build_markdown(
    has_baseline: bool,
    new_lines: list[str],
    removed_lines: list[str],
    total: int,
) -> str:
    sections: list[str] = ["#### Sorry Delta", ""]

    if not has_baseline:
        sections.append(
            f"No baseline available for comparison. "
            f"Current sorry-tainted declarations: **{total}**"
        )
        return "\n".join(sections)

    new_count = len(new_lines)
    removed_count = len(removed_lines)

    if new_count == 0 and removed_count == 0:
        sections.append(
            f"No change in sorry-tainted declarations. ({total} total)"
        )
        return "\n".join(sections)

    parts: list[str] = []
    if new_count > 0:
        s = "s" if new_count > 1 else ""
        parts.append(f"**+{new_count}** new sorry-tainted declaration{s}")
    if removed_count > 0:
        s = "s" if removed_count > 1 else ""
        parts.append(f"**-{removed_count}** removed")
    parts.append(f"({total} total)")
    sections.append(" | ".join(parts))

    if new_count > 0:
        sections.append("")
        sections.append("| Module | Declaration | Kind |")
        sections.append("|--------|-------------|------|")
        for entry in new_lines[:MAX_ROWS]:
            mod, decl, kind = parse_line(entry)
            sections.append(f"| {mod} | `{decl}` | {kind} |")
        remaining = new_count - MAX_ROWS
        if remaining > 0:
            sections.append("")
            sections.append(
                f"... and {remaining} more (see full manifest in job log)"
            )

    if removed_count > 0:
        sections.append("")
        sections.append(
            f"<details><summary>{removed_count} removed</summary>\n"
        )
        for entry in removed_lines[:MAX_ROWS]:
            mod, decl, kind = parse_line(entry)
            sections.append(f"- ~`{decl}`~ ({mod}, {kind})")
        remaining = removed_count - MAX_ROWS
        if remaining > 0:
            sections.append(f"- ... and {remaining} more")
        sections.append("\n</details>")

    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two sorry manifests and produce a markdown delta."
    )
    parser.add_argument("base_manifest", type=Path, help="Base manifest path (may not exist)")
    parser.add_argument("head_manifest", type=Path, help="Head manifest path")
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT), help="Output markdown path")
    parser.add_argument("--fail-on-new", action="store_true", help="Exit 1 if new sorries found")
    parser.add_argument("--summary", action="store_true", help="Also write to GITHUB_STEP_SUMMARY")
    parser.add_argument(
        "--include-prefix", default="",
        help="Comma/whitespace-separated module prefixes to report on "
             "(e.g. hand-written code); others are ignored",
    )
    args = parser.parse_args()

    if not args.head_manifest.exists():
        print(f"Error: head manifest not found at '{args.head_manifest}'", file=sys.stderr)
        sys.exit(2)

    prefixes = parse_prefixes(args.include_prefix)

    head_decls, _ = read_manifest(args.head_manifest)
    total = len(filter_lines(list(head_decls.values()), prefixes))

    base_decls, base_version = read_manifest(args.base_manifest)
    has_baseline = args.base_manifest.exists() and base_version is not None

    if has_baseline:
        new_keys = sorted(set(head_decls) - set(base_decls))
        removed_keys = sorted(set(base_decls) - set(head_decls))
        new_lines = filter_lines([head_decls[k] for k in new_keys], prefixes)
        removed_lines = filter_lines([base_decls[k] for k in removed_keys], prefixes)
    else:
        new_lines = []
        removed_lines = []

    body = build_markdown(has_baseline, new_lines, removed_lines, total)

    args.output.write_text(body + "\n")

    if args.summary:
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
        if summary_path:
            with open(summary_path, "a") as f:
                f.write(body + "\n")

    new_count = len(new_lines)
    removed_count = len(removed_lines)

    # When a prefix filter is active, only a newly-introduced sorry within
    # those modules warrants a comment.  Without a filter, preserve the
    # always-report behaviour so existing consumers are unaffected.
    if prefixes:
        should_comment = has_baseline and new_count > 0
    else:
        should_comment = True

    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"new-count={new_count}\n")
            f.write(f"removed-count={removed_count}\n")
            f.write(f"total-count={total}\n")
            f.write(f"comment-path={args.output}\n")
            f.write(f"should-comment={'true' if should_comment else 'false'}\n")

    scope = f" in {','.join(prefixes)}" if prefixes else ""
    print(f"Sorry delta{scope}: +{new_count} -{removed_count} ({total} total)")

    if args.fail_on_new and new_count > 0:
        print(f"::error::{new_count} new sorry-tainted declaration(s) introduced")
        sys.exit(1)


if __name__ == "__main__":
    main()

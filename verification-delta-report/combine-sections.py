#!/usr/bin/env python3
"""Combine sorry-delta and specs-delta markdown sections into a single
Verification Delta comment file.

Usage:
    python3 combine-sections.py [--sorry-delta PATH] [--specs-delta PATH]
                                [--output PATH]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

DEFAULT_OUTPUT = ".verification-delta-comment.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine verification delta sections into one PR comment."
    )
    parser.add_argument(
        "--sorry-delta", type=Path, default=Path(".sorry-delta-section.md"),
        help="Sorry delta markdown section",
    )
    parser.add_argument(
        "--specs-delta", type=Path, default=None,
        help="Specs delta markdown section (omit to skip)",
    )
    parser.add_argument(
        "--output", type=Path, default=Path(DEFAULT_OUTPUT),
        help="Combined output file",
    )
    args = parser.parse_args()

    sections: list[str] = ["### Verification Delta", ""]

    if args.sorry_delta.exists():
        sections.append(args.sorry_delta.read_text().strip())
    else:
        sections.append("#### Sorry Delta\n\nNo sorry delta data available.")

    if args.specs_delta and args.specs_delta.exists():
        content = args.specs_delta.read_text().strip()
        if content:
            sections.append("")
            sections.append(content)

    body = "\n".join(sections) + "\n"
    args.output.write_text(body)

    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"comment-path={args.output}\n")

    print(f"Verification delta comment written to {args.output}")


if __name__ == "__main__":
    main()

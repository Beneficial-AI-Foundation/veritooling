#!/usr/bin/env python3
"""Dependency-graph insights for one blueprint extract: closure, ranking, index.

The verso-blueprint "Blueprint Summary" pages (e.g.
https://leanprover.github.io/verso-blueprint/.../verso-carleson/Blueprint-Summary/)
show more than a burn-up: a per-entry closed/incomplete/sorry/no-proof split,
separate "most used in statements" / "most used in proofs" rankings, and an
entry index. This is our reproduction of that view from ``bp_graph``'s graph
model -- entirely recomputed from the extract, not a copy of the site's own
numbers.

Two things it can NOT reproduce, checked against real manifests (not just
inferred):

* The Lemma / Theorem / Proposition split -- exhaustively confirmed absent from
  every field on every real manifest node we have (``kind`` is only ever
  "definition"/"theorem"; ``title`` only ever prefixes "Definition"/"Theorem").
  Not a probe-leanblueprint gap: the data simply isn't in the JSON graph model
  anywhere, on any project.
* "Missing informal coverage" -- available only via ``--manifest``, and only
  where a CURRENT raw ``blueprint-manifest.json`` exists at the SAME commit as
  the extract (see ``verso_manifest.py``). Without ``--manifest`` this section
  is omitted, not silently reported as zero.

The closure split is computed twice -- ``claimed`` (the blueprint's own
bookkeeping, exact per ``docs/SCHEMA.md``) and ``machine`` (our independent
probe-lean-backed cross-check) -- see ``bp_graph.closure_summary``.

Usage:
    blueprint_insights.py <extract.json>                         # JSON report
    blueprint_insights.py <extract.json> --table                 # human-readable
    blueprint_insights.py <extract.json> --html -o report.html   # standalone page
    blueprint_insights.py <extract.json> --manifest m1.json m2.json --table
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

import bp_graph
import report_style
import verso_manifest


def _most_used_by(
    graph: bp_graph.Graph, downstream, indeg, use_kind: str, top_n: int
) -> list[dict]:
    """Top labels ranked by direct ``use_kind`` ("statement" or "proof") uses,
    ties broken by downstream unlocks -- mirrors the live Blueprint-Summary
    page's separate "most used in statements" / "most used in proofs" lists,
    each sorted by that column's own direct-use count, not by downstream
    impact. Confirmed at matching commits (KVAC, noperthedron): per-node
    counts agree exactly with the live page; only the combined single-list
    ranking this used to produce (sorted by downstream unlocks) picked a
    different top-N and order."""
    labels = [label for label in graph.nodes if indeg[label][use_kind] > 0]
    ranked = sorted(
        labels,
        key=lambda label: (indeg[label][use_kind], downstream[label]),
        reverse=True,
    )[:top_n]
    return [
        {
            "label": label,
            "statement_uses": indeg[label]["statement"],
            "proof_uses": indeg[label]["proof"],
            "downstream_unlocks": downstream[label],
        }
        for label in ranked
    ]


def build_report(graph: bp_graph.Graph, top_n: int = 10, warnings_by_label=None) -> dict:
    closure = bp_graph.closure_summary(graph)
    downstream = bp_graph.downstream_counts(graph)
    indeg = bp_graph.in_degree(graph)
    acted = sorted(bp_graph.actionable(graph))

    report = {
        "source": graph.source,
        "closure": closure,
        "actionable": acted,
        "actionable_count": len(acted),
        "most_used_statements": _most_used_by(graph, downstream, indeg, "statement", top_n),
        "most_used_proofs": _most_used_by(graph, downstream, indeg, "proof", top_n),
        "entry_index": [
            {
                "label": label,
                "kind": n.kind,
                "title": n.title,
                "statement_status": n.stmt_status,
                "proof_status": n.proof_status,
                "bound": n.bound,
            }
            for label, n in sorted(graph.nodes.items())
        ],
    }
    if warnings_by_label is not None:
        missing = [
            lb for lb in graph.nodes if warnings_by_label.get(lb, {}).get("leanOnlyNoStatement")
        ]
        report["missing_informal_coverage"] = sorted(missing)
    return report


def _format_table(report: dict) -> str:
    c = report["closure"]
    lines = [
        f"Source: {report['source'].get('repo', '?')} @ "
        f"{(report['source'].get('commit', '') or '')[:8]}",
        "",
        f"Theorem entries: {c['thm_total']}",
        "  claimed (blueprint's own bookkeeping):",
        f"    closed:            {c['claimed']['closed']}",
        f"    incomplete-deps:   {c['claimed']['incomplete-deps']}",
        f"    sorry:             {c['claimed']['sorry']}",
        f"    no-proof:          {c['claimed']['no-proof']}",
        "  machine (probe-lean cross-check):",
        f"    closed:            {c['machine']['closed']}",
        f"    incomplete-deps:   {c['machine']['incomplete-deps']}",
        f"    sorry:             {c['machine']['sorry']}",
        f"    no-proof:          {c['machine']['no-proof']}",
    ]
    if c["machine_cycles"]:
        lines.append(f"  WARNING: dependency cycle(s) detected at: {c['machine_cycles']}")
    lines += [
        "",
        f"Actionable (statement ready, deps formalized): {report['actionable_count']}",
    ]
    if report["actionable"]:
        lines += [f"  {label}" for label in report["actionable"][:10]]
    lines += ["", "Most used in statements (top entries by statement uses):"]
    for m in report["most_used_statements"]:
        lines.append(
            f"  {m['label']:<40} stmt-uses={m['statement_uses']:<4} "
            f"proof-uses={m['proof_uses']:<4} downstream={m['downstream_unlocks']}"
        )
    lines += ["", "Most used in proofs (top entries by proof uses):"]
    for m in report["most_used_proofs"]:
        lines.append(
            f"  {m['label']:<40} proof-uses={m['proof_uses']:<4} "
            f"stmt-uses={m['statement_uses']:<4} downstream={m['downstream_unlocks']}"
        )
    if "missing_informal_coverage" in report:
        mi = report["missing_informal_coverage"]
        lines += ["", f"Missing informal coverage: {len(mi)} entr{'y' if len(mi) == 1 else 'ies'}"]
        lines += [f"  {label}" for label in mi[:10]]
    else:
        lines += ["", "Missing informal coverage: not checked (no --manifest given)"]
    return "\n".join(lines)


# The four claimed/machine buckets, in display order, each with a status-palette
# swatch. `incomplete-deps` and `sorry` use the status palette's `warning`/
# `critical` roles as SWATCH fills only (never as text color -- `warning` is
# sub-3:1 on a light surface by design, see report_style.py); the swatch +
# adjacent label is the accessibility pairing the palette calls for.
_BUCKET_SWATCH = (
    ("closed", report_style.GOOD),
    ("incomplete-deps", report_style.WARNING),
    ("sorry", report_style.CRITICAL),
    ("no-proof", report_style.INK_MUTED),
)


def _stat_tiles(counts: dict) -> str:
    tiles = []
    for key, colour in _BUCKET_SWATCH:
        tiles.append(
            '<div class="tile">'
            f'<span class="swatch" style="background:{colour}"></span>'
            f'<span class="tile-value">{counts[key]}</span>'
            f'<span class="tile-label">{html.escape(key)}</span>'
            "</div>"
        )
    return f'<div class="tiles">{"".join(tiles)}</div>'


def _stacked_bar(counts: dict, total: int) -> str:
    if total == 0:
        return '<p class="note muted">No theorem-kind entries.</p>'
    segments = []
    for key, colour in _BUCKET_SWATCH:
        n = counts[key]
        if n == 0:
            continue
        pct = 100 * n / total
        label = f"{key} {n}" if pct >= 12 else ""
        segments.append(
            f'<div class="seg" style="width:{pct:.3f}%;background:{colour}" '
            f'title="{html.escape(key)}: {n} ({pct:.0f}%)">{html.escape(label)}</div>'
        )
    return f'<div class="bar">{"".join(segments)}</div>'


def _entry_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    """``columns`` is ``[(field, header), ...]``; ``label`` is always emitted as
    a `<code>` cell first."""
    head = "<th>label</th>" + "".join(f"<th>{html.escape(h)}</th>" for _, h in columns)
    body = []
    for r in rows:
        cells = "".join(f"<td>{html.escape(str(r[f]))}</td>" for f, _ in columns)
        body.append(f"<tr><td><code>{html.escape(str(r['label']))}</code></td>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


_HTML_CSS = (
    report_style.BASE_CSS
    + f"""
.tiles {{ display: flex; gap: 1rem; margin: .5rem 0 1rem; flex-wrap: wrap; }}
.tile {{ background: {report_style.SURFACE}; border: 1px solid {report_style.GRIDLINE};
  border-radius: 6px; padding: .5rem .9rem; min-width: 6.5rem; }}
.tile .swatch {{ display: inline-block; width: .6rem; height: .6rem; border-radius: 2px;
  margin-right: .35rem; }}
.tile-value {{ font-size: 1.3rem; font-weight: 600; }}
.tile-label {{ display: block; color: {report_style.INK_SECONDARY}; font-size: .8rem;
  margin-left: 1rem; }}
.bar {{ display: flex; height: 1.4rem; border-radius: 4px; overflow: hidden;
  background: {report_style.GRIDLINE}; margin: .35rem 0 1rem; }}
.seg {{ display: flex; align-items: center; justify-content: center; color: #fff;
  font-size: .72rem; font-weight: 600; white-space: nowrap; overflow: hidden;
  border-right: 2px solid {report_style.PAGE}; }}
.seg:last-child {{ border-right: none; }}
.chips {{ display: flex; gap: .4rem; flex-wrap: wrap; margin: .5rem 0 1rem; }}
.chip {{ background: {report_style.SURFACE}; border: 1px solid {report_style.GRIDLINE};
  border-radius: 999px; padding: .15rem .7rem; font-family: ui-monospace, monospace;
  font-size: .82rem; }}
.warn-banner {{ background: #fdecea; border: 1px solid {report_style.CRITICAL};
  color: {report_style.CRITICAL}; border-radius: 6px; padding: .5rem .8rem; margin: .5rem 0; }}
.muted {{ color: {report_style.INK_MUTED}; }}
details summary {{ cursor: pointer; font-weight: 600; margin: .5rem 0; }}
"""
)


def _format_html(report: dict, top_n: int) -> str:
    src = report["source"]
    title = src.get("repo", "?").rstrip("/").removesuffix(".git").split("/")[-1]
    commit = (src.get("commit", "") or "")[:8]
    c = report["closure"]

    sections = [
        f"<h1>{html.escape(title)} &mdash; Blueprint insights</h1>",
        f'<p class="note">Source: {html.escape(src.get("repo", "?"))} '
        f'<span class="muted">@ {html.escape(commit)}</span> &middot; '
        f"{c['thm_total']} theorem-kind entries</p>",
    ]
    if c["machine_cycles"]:
        sections.append(
            '<p class="warn-banner">&#9888; dependency cycle(s) detected at: '
            f"{html.escape(', '.join(c['machine_cycles']))}</p>"
        )

    sections.append("<h2>Claimed (blueprint's own bookkeeping)</h2>")
    sections.append(_stat_tiles(c["claimed"]))
    sections.append(_stacked_bar(c["claimed"], c["thm_total"]))
    sections.append("<h2>Machine (probe-lean cross-check)</h2>")
    sections.append(_stat_tiles(c["machine"]))
    sections.append(_stacked_bar(c["machine"], c["thm_total"]))

    sections.append(f"<h2>Actionable ({report['actionable_count']})</h2>")
    if report["actionable"]:
        chips = "".join(
            f'<span class="chip">{html.escape(lb)}</span>' for lb in report["actionable"]
        )
        sections.append(f'<div class="chips">{chips}</div>')
    else:
        sections.append('<p class="note muted">None.</p>')

    sections.append(f"<h2>Most used in statements (top {top_n})</h2>")
    sections.append(
        _entry_table(
            report["most_used_statements"],
            [
                ("statement_uses", "stmt uses"),
                ("proof_uses", "proof uses"),
                ("downstream_unlocks", "downstream"),
            ],
        )
    )
    sections.append(f"<h2>Most used in proofs (top {top_n})</h2>")
    sections.append(
        _entry_table(
            report["most_used_proofs"],
            [
                ("proof_uses", "proof uses"),
                ("statement_uses", "stmt uses"),
                ("downstream_unlocks", "downstream"),
            ],
        )
    )

    if "missing_informal_coverage" in report:
        mi = report["missing_informal_coverage"]
        sections.append(f"<h2>Missing informal coverage ({len(mi)})</h2>")
        if mi:
            chips = "".join(f'<span class="chip">{html.escape(lb)}</span>' for lb in mi)
            sections.append(f'<div class="chips">{chips}</div>')
        else:
            sections.append('<p class="note muted">None.</p>')
    else:
        sections.append(
            '<h2>Missing informal coverage</h2><p class="note muted">'
            "Not checked (no --manifest given).</p>"
        )

    sections.append(f"<details><summary>Entry index ({len(report['entry_index'])})</summary>")
    sections.append(
        _entry_table(
            report["entry_index"],
            [
                ("kind", "kind"),
                ("statement_status", "statement"),
                ("proof_status", "proof"),
                ("bound", "bound"),
            ],
        )
    )
    sections.append("</details>")

    body = "\n".join(sections)
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<title>{html.escape(title)} &mdash; Blueprint insights</title>
<style>{_HTML_CSS}</style></head>
<body>
{body}
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Dependency-graph insights for one blueprint extract.")
    p.add_argument(
        "input", type=Path, help="probe-leanblueprint/extract envelope (.json/.json.gz)."
    )
    p.add_argument(
        "--manifest",
        type=Path,
        nargs="+",
        help="Raw blueprint-manifest.json file(s) (same commit as INPUT) for the "
        "missing-informal-coverage section. Omit if none is available.",
    )
    p.add_argument("--top", type=int, default=10, help="How many entries in the most-used ranking.")
    p.add_argument("--table", action="store_true", help="Human-readable table instead of JSON.")
    p.add_argument(
        "--html", action="store_true", help="Standalone HTML report instead of JSON/table."
    )
    p.add_argument(
        "-o", "--output", type=Path, help="Write to this file instead of stdout (any format)."
    )
    args = p.parse_args(argv)

    if not args.input.is_file():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    if args.manifest:
        bad = [str(m) for m in args.manifest if not m.is_file()]
        if bad:
            print(f"Error: manifest file(s) not found: {', '.join(bad)}", file=sys.stderr)
            return 1

    graph = bp_graph.build_graph_file(args.input)
    warnings_by_label = (
        verso_manifest.load_manifest_warnings(args.manifest) if args.manifest else None
    )
    report = build_report(graph, top_n=args.top, warnings_by_label=warnings_by_label)

    if args.html:
        out = _format_html(report, args.top)
    elif args.table:
        out = _format_table(report)
    else:
        out = json.dumps(report, indent=2)

    if args.output:
        args.output.write_text(out, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

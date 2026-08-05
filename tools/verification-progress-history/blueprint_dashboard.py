#!/usr/bin/env python3
"""Cross-project blueprint dashboard: one comparable view over several extracts.

Runs the ``bp_graph`` model over each input extract, renders its dependency
graph (via ``plot_depgraph``), and writes a static ``index.html`` linking them
with a comparison table. Every figure is recomputed from the extract per-node
data -- never a summary sidecar (schema-2.0 side fields are unreliable).

The table is keyed on **fractions**, not raw counts: blueprint-node granularity
differs across projects (one node bundles a variable number of Lean decls), so
raw totals are apples-to-oranges. Two fractions are shown and kept distinct
(see the plan's "Terminology"):

* **claimed** -- the blueprint's own ``fully-proved`` claim over theorems.
* **machine-verified** -- probe-lean's ``verification-status`` rollup landing on
  ``verified`` (the graph's solid green). NOT the sidecar's
  ``fraction-probe-lean-confirmed`` (a "not-refuted" bar).

Each project also gets its own ``blueprint_insights.py --html`` report
(closed/incomplete/sorry/no-proof split, most-used rankings, entry index),
written alongside its graph and linked from the table.

Usage:
    blueprint_dashboard.py <extract...> -o out/            # svgs + index.html
    blueprint_dashboard.py /tmp/verso-*.extract.json -o out/
"""

from __future__ import annotations

import argparse
import html
import shutil
import sys
from pathlib import Path

import blueprint_insights
import bp_graph
import plot_depgraph
import report_style


def _project_name(graph: bp_graph.Graph, input_path: Path) -> str:
    repo = graph.source.get("repo", "")
    if repo:
        return repo.rstrip("/").removesuffix(".git").split("/")[-1]
    return input_path.name.split(".")[0]


def _row(
    name: str,
    graph: bp_graph.Graph,
    s: dict,
    svg_href: str | None,
    insights_href: str,
) -> str:
    commit = (graph.source.get("commit", "") or "")[:8]
    mism = s["by_state"].get("mismatch", 0)
    mism_cell = f'<td class="warn">{mism}</td>' if mism else "<td>0</td>"
    link = f'<a href="{html.escape(svg_href)}">graph</a>' if svg_href else "&mdash;"
    insights_link = f'<a href="{html.escape(insights_href)}">insights</a>'
    return (
        "<tr>"
        f"<td>{html.escape(name)}</td>"
        f"<td class=commit>{html.escape(commit)}</td>"
        f"<td>{s['nodes_total']}</td>"
        f"<td>{s['def_total']}</td>"
        f"<td>{s['thm_total']}</td>"
        f"<td>{s['claimed_fraction']:.0%}</td>"
        f"<td class=mv>{s['machine_verified_fraction']:.0%}</td>"
        f"{mism_cell}"
        f"<td>{link}</td>"
        f"<td>{insights_link}</td>"
        "</tr>"
    )


_CSS = report_style.BASE_CSS


def build_dashboard(inputs: list[Path], out_dir: Path, title: str, render_svg: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, rendered = [], 0
    for path in inputs:
        graph = bp_graph.build_graph_file(path)
        s = bp_graph.summary(graph)
        name = _project_name(graph, path)
        # Always emit the DOT (text: reviewable and regenerable without graphviz);
        # render the SVG too when `dot` is available and link to it in preference.
        dot = plot_depgraph.to_dot(graph, title=name)
        (out_dir / f"{name}.dot").write_text(dot, encoding="utf-8")
        svg_href = f"{name}.dot"
        if render_svg and shutil.which("dot"):
            svg_path = out_dir / f"{name}.svg"
            plot_depgraph._render(dot, svg_path, "svg")
            svg_href = svg_path.name
            rendered += 1

        insights_report = blueprint_insights.build_report(graph)
        insights_html = blueprint_insights._format_html(insights_report, top_n=10)
        (out_dir / f"{name}.insights.html").write_text(insights_html, encoding="utf-8")

        rows.append(_row(name, graph, s, svg_href, f"{name}.insights.html"))

    page = f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<title>{html.escape(title)}</title><style>{_CSS}</style></head>
<body>
<h1>{html.escape(title)}</h1>
<table>
<caption>Blueprint formalization progress ({len(inputs)} projects)</caption>
<thead><tr>
<th>project</th><th>commit</th><th>nodes</th><th>def</th><th>thm</th>
<th>claimed</th><th>machine-verified</th><th>mismatch</th><th>graph</th><th>insights</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table>
<p class=note><b>claimed</b> = the blueprint's own <code>fully-proved</code> claim over
theorems. <b>machine-verified</b> = probe-lean's <code>verification-status</code> rollup
landing on <code>verified</code> (no sorry / axiom / failure in the node's bindings) &mdash;
a stricter, machine-checked bar, and the graphs' solid green. <b>mismatch</b> counts nodes
claimed proved but refuted by the machine. Trust detection is node-local (cross-node axiom
reliance is not caught).</p>
</body></html>
"""
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"Wrote {out_dir / 'index.html'} ({len(inputs)} projects, {rendered} SVGs)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cross-project blueprint dashboard.")
    p.add_argument("inputs", type=Path, nargs="+", help="extract envelopes (.json/.json.gz).")
    p.add_argument("-o", "--output", type=Path, required=True, help="Output directory.")
    p.add_argument("--title", default="Blueprint formalization dashboard", help="Page title.")
    p.add_argument("--no-svg", action="store_true", help="Emit DOT only, skip `dot` SVG render.")
    args = p.parse_args(argv)

    missing = [str(i) for i in args.inputs if not i.is_file()]
    if missing:
        print(f"Error: file(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 1

    return build_dashboard(args.inputs, args.output, args.title, render_svg=not args.no_svg)


if __name__ == "__main__":
    raise SystemExit(main())

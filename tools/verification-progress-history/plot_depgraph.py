#!/usr/bin/env python3
"""Render a blueprint dependency graph from one extract envelope.

Emits Graphviz **DOT** (dependency-free, portable, reviewable as text); if an
``.svg`` / ``.png`` output is asked for and ``dot`` is on PATH, it shells out to
render it, mirroring ``plot_progress.py``'s optional PNG step.

The graph reproduces the leanblueprint / verso dependency graph plus the two
things the native tools can't show (see ``blueprint-depgraph-plan.md``):

* **machine-verified** colouring -- solid green means probe-lean's own
  ``verification-status`` rollup lands on ``verified`` (no sorry / axiom /
  failure in the node's bindings), not a hand-toggled ``\\leanok``; and
* **mismatch** flags -- a node the blueprint claims proved but the machine
  refutes (sorry / failed).

Node grouping and colour come from ``bp_graph``. Solid edges are statement
``\\uses``; dashed edges are proof ``\\uses`` / ``\\proves``.

Usage:
    plot_depgraph.py <extract.json[.gz]>            # DOT to stdout
    plot_depgraph.py <extract.json> -o graph.svg    # render via `dot`
    plot_depgraph.py <extract.json> -o graph.dot    # DOT to a file
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import bp_graph
from bp_graph import node_state

# state -> Graphviz node attributes. Fills use the plot_progress.py palette; the
# two "bold" states (machine-verified, mismatch, trusted) are the value-add.
GREEN, BLUE, PURPLE, RED = "#1F8A65", "#2E79B5", "#7B64B8", "#C0392B"
BLACK, WHITE, GREY = "#1A1A1A", "#FFFFFF", "#333333"


def _style(fill, border, *, style="filled", font=GREY, penwidth=None):
    d = dict(fillcolor=fill, color=border, style=style, fontcolor=font)
    if penwidth:
        d["penwidth"] = penwidth
    return d


STATE_STYLE = {
    "not-ready": _style(WHITE, "#888899", style="filled,dashed"),
    "ready": _style(WHITE, GREEN),
    "statement-formalized": _style("#DCEAF6", BLUE, font=BLACK),
    "proved-claimed": _style("#BFE3D3", GREEN, style="filled,diagonals", font=BLACK),
    "machine-verified": _style(GREEN, GREEN, font=WHITE),
    "trusted": _style(GREEN, PURPLE, font=WHITE, penwidth="2.5"),
    "mismatch": _style("#F5C6C0", RED, font=BLACK, penwidth="2.5"),
    "failed": _style(RED, RED, font=WHITE),
}

# Human labels for the legend (state -> one-line meaning).
STATE_LABEL = {
    "not-ready": "not ready to formalize",
    "ready": "ready to formalize",
    "statement-formalized": "statement formalized",
    "proved-claimed": "proved (claimed, unconfirmed)",
    "machine-verified": "machine-verified (green)",
    "trusted": "trusted (axiom / external)",
    "mismatch": "MISMATCH: claimed proved, refuted",
    "failed": "failed (elaboration error)",
}


def _dot_str(s: str) -> str:
    """Escape a string for a DOT double-quoted literal."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _node_text(n: bp_graph.Node) -> str:
    """Display label: the blueprint label, de-guillemeted.

    Deliberately NOT ``blueprint-title`` ("Theorem 13.4.7"): that is the
    document's auto-numbering, not a name. ``blueprint-label`` is the
    human-authored `\\label{...}` and is always single-valued per node --
    unlike the underlying Lean declaration(s), which a node can bind more than
    one of (e.g. a security experiment split across an adversary type, an
    implementation, and an experiment function all sharing one blueprint
    statement).
    """
    return n.label.strip("«»")


def _attrs(d: dict) -> str:
    return ", ".join(f'{k}="{_dot_str(v)}"' for k, v in d.items())


def _header(graph: bp_graph.Graph, s: dict) -> str:
    src = graph.source
    repo = src.get("repo", "?")
    commit = (src.get("commit", "") or "")[:8]
    st = s["by_state"]
    dropped = ", ".join(f"{r}={c}" for r, c in s["dropped"].items() if c)
    lines = [
        f"{repo} @ {commit}",
        f"schema {graph.schema} v{graph.schema_version}",
        f"{s['nodes_total']} nodes ({s['def_total']} def, {s['thm_total']} thm)  "
        f"{s['edges']} edges",
        f"theorems: claimed proved {s['thm_claimed_proved']}/{s['thm_total']} "
        f"({s['claimed_fraction']:.0%})   "
        f"machine-verified {s['thm_machine_verified']}/{s['thm_total']} "
        f"({s['machine_verified_fraction']:.0%})",
        "states: " + "  ".join(f"{k}={st[k]}" for k in bp_graph.STATES if st[k]),
    ]
    if st.get("mismatch"):
        lines.append(f"WARNING: {st['mismatch']} node(s) claim proved but the machine refutes")
    if dropped:
        lines.append(f"edges dropped: {dropped}")
    lines.append("caveat: trust detection is node-local (cross-node axiom reliance not caught)")
    # \l = left-justified line break in DOT.
    return "\\l".join(_dot_str(x) for x in lines) + "\\l"


def _legend(present: set[str]) -> list[str]:
    """A legend cluster showing only the states that appear in this graph."""
    out = [
        "  subgraph cluster_legend {",
        '    label="legend"; fontsize=11; style=dashed; color="#BBBBBB";',
    ]
    prev = None
    for state in bp_graph.STATES:
        if state not in present:
            continue
        attrs = dict(STATE_STYLE[state])
        attrs["label"] = STATE_LABEL[state]
        attrs["shape"] = "box"
        attrs["fontsize"] = "9"
        nid = f"leg_{state.replace('-', '_')}"
        out.append(f"    {nid} [{_attrs(attrs)}];")
        if prev is not None:
            out.append(f"    {prev} -> {nid} [style=invis];")
        prev = nid
    out.append("  }")
    return out


def to_dot(graph: bp_graph.Graph, title: str | None = None) -> str:
    s = bp_graph.summary(graph)
    ids = {label: f"n{i}" for i, label in enumerate(sorted(graph.nodes))}
    present = {node_state(n) for n in graph.nodes.values()}

    lines = ["digraph blueprint {"]
    lines.append(
        '  graph [rankdir=TB, labelloc="t", fontname="Helvetica", fontsize=11, splines=true];'
    )
    lines.append('  node [shape=box, fontname="Helvetica", fontsize=10];')
    header = _header(graph, s)
    if title:
        header = _dot_str(title) + "\\l" + header
    lines.append(f'  label="{header}";')

    for label in sorted(graph.nodes):
        n = graph.nodes[label]
        attrs = dict(STATE_STYLE[node_state(n)])
        attrs["label"] = _node_text(n)
        lines.append(f"  {ids[label]} [{_attrs(attrs)}];")

    for e in graph.edges:
        if e.src not in ids or e.dst not in ids:
            continue
        style = "dashed" if e.kind == "proof" else "solid"
        lines.append(f"  {ids[e.src]} -> {ids[e.dst]} [style={style}];")

    lines.extend(_legend(present))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render(dot: str, out: Path, fmt: str) -> None:
    """Shell out to `dot` to render DOT into svg/png; needs graphviz on PATH."""
    exe = shutil.which("dot")
    if exe is None:
        raise SystemExit(
            f"Error: '{fmt}' output needs Graphviz `dot` on PATH "
            "(install graphviz), or write a .dot file instead."
        )
    proc = subprocess.run(
        [exe, f"-T{fmt}", "-o", str(out)],
        input=dot.encode("utf-8"),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"Error: dot failed: {proc.stderr.decode('utf-8', 'replace')}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render a blueprint dependency graph (DOT/SVG/PNG).")
    p.add_argument(
        "input", type=Path, help="probe-leanblueprint/extract envelope (.json or .json.gz)."
    )
    p.add_argument("-o", "--output", type=Path, help="Output file; format inferred from extension.")
    p.add_argument("--format", choices=("dot", "svg", "png"), help="Override output format.")
    p.add_argument("--title", help="Extra title line above the header.")
    args = p.parse_args(argv)

    if not args.input.is_file():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    graph = bp_graph.build_graph_file(args.input)
    dot = to_dot(graph, title=args.title)

    fmt = args.format
    if fmt is None and args.output is not None:
        fmt = args.output.suffix.lstrip(".").lower() or "dot"
    if fmt is None:
        fmt = "dot"

    if fmt == "dot":
        if args.output is not None:
            args.output.write_text(dot, encoding="utf-8")
        else:
            sys.stdout.write(dot)
    else:
        if args.output is None:
            print("Error: svg/png output needs -o OUTPUT", file=sys.stderr)
            return 1
        _render(dot, args.output, fmt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

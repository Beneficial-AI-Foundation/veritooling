# Guide: blueprint dependency graph, insights & dashboard

**The question this answers:** for one snapshot of a Lean blueprint project (a
single commit), what does its dependency graph look like, what is closed versus
blocked, and how do several projects compare on one page?

Unlike the [history burn-up](history-burnup.md), this journey is about one
extract, not a time series. It reads a `probe-leanblueprint extract` envelope and
recomputes everything from its per-node data.

**Scripts:**

```
bp_graph.py               build the graph model (nodes/edges/state/closure) from one extract
  plot_depgraph.py         render the graph as Graphviz DOT (SVG/PNG if `dot` is present)
  blueprint_insights.py    closure split, most-used rankings, entry index, informal coverage
    verso_manifest.py      per-node warnings (missing informal coverage) from a raw manifest
    report_style.py        shared HTML palette and CSS tokens
  blueprint_dashboard.py   cross-project index.html comparing several extracts
```

`bp_graph.py` is the shared model; the other three are views over it.

## The input is an extract JSON, and it is not committed

Every script here takes a `probe-leanblueprint/extract` envelope
(`.json`/`.json.gz`). Those envelopes are not committed in `data/`: only the
rendered outputs (`depgraph.*`, `insights.*`, `index.html`) are, because a full
extract needs a built Lean project and is large. So you can read the committed
outputs directly, but reproducing them needs an extract you generate yourself.

Read the committed KVAC snapshot (blueprint graph plus insights at commit
`ab91ef60`):

```bash
xdg-open data/kvac-model/depgraph.svg
xdg-open data/kvac-model/insights.html
cat     data/kvac-model/insights.txt
```

The cross-project dashboard is `data/all-blueprints/index.html`.

## Generate an extract, then reproduce the outputs

Point `probe-leanblueprint extract` at a clone whose dependencies are already
built (`.lake/build` has `.olean` files), so it reads the existing
`blueprint-manifest.json` under `docs/_out/site` instead of re-rendering:

```bash
cd /path/to/the/lean/project
probe-leanblueprint extract . --no-render -o /tmp/kvac.extract.json
```

Then run the views from the tool's directory:

```bash
# Graph: DOT on stdout, or SVG/PNG when `dot` is present.
python3 plot_depgraph.py /tmp/kvac.extract.json -o /tmp/depgraph.svg

# Insights: plain table, or a standalone HTML page.
python3 blueprint_insights.py /tmp/kvac.extract.json --table
python3 blueprint_insights.py /tmp/kvac.extract.json --html -o /tmp/insights.html

# Several projects: one cross-project page plus a graph and insights page each.
python3 blueprint_dashboard.py /tmp/verso-*.extract.json -o /tmp/site/
```

`blueprint_insights.py` can cross-check missing informal coverage if you also
pass the raw chapter manifest(s) at the same commit via `--manifest`; without it
that one section is omitted, not reported as zero.

To feed these from history rather than a one-off extract, run the sampler with
`--archive-extracts`. Each `ok` sample's envelope is gzipped to
`data/<name>/extracts/<commit>.json.gz`, which these scripts read directly.

## What to look at in the outputs

**Graph** (`depgraph.svg`): nodes are blueprint labels; solid edges are statement
`\uses`, dashed are proof `\uses`/`\proves`. Solid green means probe-lean's own
rollup says machine-verified (stricter than a hand-toggled `\leanok`); a red
outline means the blueprint claims proved but the machine refutes (near-zero on
code-derived Verso blueprints).

**Insights** (`insights.txt`/`.html`), using the committed KVAC snapshot as the
worked example:

- **claimed vs machine** closure split (closed / incomplete-deps / sorry /
  no-proof). On KVAC the two agree (1 closed, 2 incomplete-deps, 14 no-proof); on
  larger projects like carleson the machine column is stricter.
- **actionable**: statement `ready` with every dependency already formalized, the
  unblocked next steps (KVAC lists 10).
- **most used in statements** and **most used in proofs**: two rankings, each by
  that column's own direct-use count.
- a **dependency cycle** is flagged rather than silently mis-closed; KVAC's has
  one (`attribute_lifting` / `single_attribute_mac`).
- **missing informal coverage**: shown only when a `--manifest` was supplied.

**Dashboard** (`index.html`): a fractions-keyed table (node granularity differs
across projects) showing **claimed** beside the stricter **machine-verified**.

Full definitions and caveats (node grouping, node-local trust detection, what the
model cannot show) are in the
[tool README](../README.md#dependency-graph--cross-project-dashboard).

For how these outputs measure up against verso-blueprint's own published graph
and Blueprint Summary pages (same commit, four reference blueprints), see
[verso-blueprint-comparison.md](verso-blueprint-comparison.md).

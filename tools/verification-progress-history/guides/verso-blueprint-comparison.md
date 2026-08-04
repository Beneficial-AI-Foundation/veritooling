# Guide: our reproduction vs verso-blueprint (accuracy comparison)

**The question this answers:** how close is our dependency-graph + insights
reproduction to what [verso-blueprint](https://github.com/leanprover/verso-blueprint)
itself publishes? verso-blueprint ships four reference blueprints, each with a
live **Dependency Graph** and a **Blueprint Summary** page. Our
[`bp_graph.py` chain](graph-and-dashboard.md) recomputes both from a
`probe-leanblueprint` extract. This page puts the two side by side, for all
four, at the exact commit verso pins.

Both sides are the **same upstream commit** (verso pins its reference blueprints
via an `ejgallego/verso-*` wrapper whose git submodule fixes the upstream SHA;
our extract runs against a clone at that same SHA), so number differences are
real methodology differences, not commit drift.

| Project | Upstream commit | Lean | verso pages |
|---------|-----------------|------|-------------|
| Carleson | `8e93bee1` | v4.31.0 | [summary](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.31.0/verso-carleson/Blueprint-Summary/) · [graph](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.31.0/verso-carleson/Dependency-Graph/) |
| Sphere-Packing | `1828993f` | v4.31.0 | [summary](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.31.0/spherepackingblueprint/Blueprint-Summary/) · [graph](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.31.0/spherepackingblueprint/Dependency-Graph/) |
| FLT | `ee47fd2a` | v4.32.0-rc1 | [summary](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.32.0/verso-flt/Blueprint-Summary/) · [graph](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.32.0/verso-flt/Dependency-Graph/) |
| Noperthedron | `83502054` | v4.32.0-rc1 | [summary](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.32.0/noperthedron/Blueprint-Summary/) · [graph](https://leanprover.github.io/verso-blueprint/reference-blueprints/v4.32.0/noperthedron/Dependency-Graph/) |

## Headline: where we match, where we differ

**Match, to the unit.** Whenever an entry is present on both sides, our
`claimed` closure buckets and our downstream-unlock counts equal verso's. On
Carleson, Sphere-Packing, and FLT the shared-entry `closed`, `deps incomplete`,
and `sorry` counts agree exactly (closed 154/24/105, sorry 0/9/10) — Sphere-Packing
matches on all four buckets (24 / 29 / 9 / 44). Every `downstream` figure in
"most used" matches verso's. Our `Actionable` list equals verso's `Actionable
priorities` exactly on Carleson (0) and Noperthedron (9).

**Differ, and why.** Three differences. Entry-set membership and the type
taxonomy are upstream of the graph model (from how `probe-leanblueprint` extracts
the node set); the sorry gap is now mostly closed in `bp_graph` itself:

1. **Entry-set membership.** `probe-leanblueprint` keeps a slightly different
   node set than verso renders: FLT +8, Carleson +1, Sphere-Packing ±0,
   Noperthedron −11 entries. On FLT/Carleson the extra nodes are all `no-proof`;
   on Noperthedron we are missing 11 non-definition entries verso shows.
2. **Sorry detection.** verso marks an entry `sorry` when its proof exists but
   contains a `sorry`. `probe-leanblueprint` demotes that (a `code-derived`
   claim the machine can't confirm) to `blueprint-proof-status: none`, but keeps
   the original in `blueprint-source-proof-status: incomplete`. `bp_graph` reads
   that source field, so our `sorry` bucket now matches verso exactly on
   Sphere-Packing (9) and FLT (10). Noperthedron's single sorry is the exception:
   its entry is labelled `fully-proved` with a missing decl, so it lands in
   `closed`, not `sorry` — that one needs an extract bound to the upstream
   library to catch (see "Graph coloring"). Independent machine re-detection of
   sorries is also inert on these wrapper-only extracts, for the same
   decl-binding reason.
3. **Type taxonomy.** verso splits Definition / Lemma / Theorem / Corollary; we
   only carry `definition` vs `theorem`, and our headline counts "theorem
   entries" (non-definitions) while verso's total includes definitions. This is
   a genuine data gap: the finer split is absent from every field of the extract
   JSON we consume.

**Our value-add (not on verso's pages).** A `machine` column — probe-lean's
independent verification rollup, stricter than the blueprint's own `\leanok`
bookkeeping. verso shows only the claimed state. (See the caveat below: on these
wrapper-only extracts the `machine` column is degenerate.)

### Cross-project numbers

`claimed` is our reproduction of the blueprint's own bookkeeping — the column
directly comparable to verso. verso's `sorries`/`no proof`/`completed` are its
overview line; the non-definition split is its per-type rollup.

| Project | verso total | our nodes (def/thm) | Δ | closed (verso non-def / ours) | sorries (verso / ours) | actionable (verso AP / ours) |
|---------|------------:|--------------------:|--:|------------------------------:|-----------------------:|-----------------------------:|
| Carleson | 160 | 161 (0/161) | +1 | 154 / **154** | 0 / **0** | 0 / **0** |
| Sphere-Packing | 140 | 140 (34/106) | 0 | 24 / **24** | 9 / **9** | 26 / 19 |
| FLT | 237 | 245 (51/194) | +8 | 105 / **105** | 10 / **10** | 32 / 25 |
| Noperthedron | 79 | 68 (9/59) | −11 | 46 / 37 | 1 / 0 | 9 / **9** |

`Actionable` diverges on Sphere-Packing (19 vs 26) and FLT (25 vs 32) by
definition, not by error: ours counts entries whose next step is writing the
*statement* (statement ready, deps formalized), whereas verso's "Actionable
priorities" counts any next formalization step — statement *or* proof — that also
unlocks downstream. Verso's set is the broader one, so ours is a subset
(`19 ≤ 26`, `25 ≤ 32`); it coincides where the proof-next set is empty (Carleson
0, Noperthedron 9). Our `Missing informal coverage` reports 0 on all four where
verso finds 1 / 2 / 2 / 10; our `--manifest` cross-check is looking at fields the
current wrapper manifests do not populate. Both are noted, not asserted as verso
being wrong.

## Per-project side by side

Left/top is ours (`bp_graph.py` chain, current code); right/bottom is verso's
published page.

### Carleson

Overview — ours vs verso:

<img src="../data/verso-comparison/carleson.verso-summary-overview.png" width="520">

[`carleson.ours-insights.txt`](../data/verso-comparison/carleson.ours-insights.txt)

Graph — ours (Graphviz) then verso (d3):

![ours](../data/verso-comparison/carleson.ours-depgraph.png)
![verso](../data/verso-comparison/carleson.verso-depgraph.png)

**The 161-vs-160 difference is one node, and it is the single red node in verso's
graph.** verso's own manifest has 161 nodes, the same as ours; verso excludes one
from its "Total entries: 160". That node is `«nontangential-from-simple»`
(`kind: None`, `statementStatus: blocked`, `proofStatus: none`,
`warnings.unknownRef: true`) — a label other entries reach via `\uses` but that
was never given its own statement or proof. verso paints it red ("Blocked", its
legend's danger state) and drops it from the entry total; we keep it as a node and
bucket it `no-proof`. So `161 vs 160` and `no-proof 1 vs 0` are the same fact, not
two. In our graph it is the dashed white "not ready to formalize" box near
`Dirichlet-approximation`.

### Sphere-Packing

<img src="../data/verso-comparison/sphere-packing.verso-summary-overview.png" width="520">

[`sphere-packing.ours-insights.txt`](../data/verso-comparison/sphere-packing.ours-insights.txt)

![ours](../data/verso-comparison/sphere-packing.ours-depgraph.png)
![verso](../data/verso-comparison/sphere-packing.verso-depgraph.png)

### FLT

<img src="../data/verso-comparison/flt.verso-summary-overview.png" width="520">

[`flt.ours-insights.txt`](../data/verso-comparison/flt.ours-insights.txt)

![ours](../data/verso-comparison/flt.ours-depgraph.png)
![verso](../data/verso-comparison/flt.verso-depgraph.png)

### Noperthedron

<img src="../data/verso-comparison/noperthedron.verso-summary-overview.png" width="520">

[`noperthedron.ours-insights.txt`](../data/verso-comparison/noperthedron.ours-insights.txt)

![ours](../data/verso-comparison/noperthedron.ours-depgraph.png)
![verso](../data/verso-comparison/noperthedron.verso-depgraph.png)

## Graph coloring

verso colors a node green from the blueprint's own `\leanok`. Our graph adds a
stricter distinction: **solid** green is probe-lean machine-verified, **diagonal
light-green** is claimed-proved but machine-unconfirmed. On these four extracts
almost every node is diagonal light-green: the extract was run against the verso
**wrapper** project, whose modules are the blueprint document, not the upstream
Lean library, so probe-lean cannot bind blueprint nodes to their declarations
(`decl-missing`) and the `machine` column collapses to zero. This is an artifact
of the wrapper-only extract, not of `bp_graph`. On an extract built against the
upstream library (e.g. the committed KVAC snapshot in
[`../data/kvac-model/`](../data/kvac-model/)) the `machine` column and solid-green
nodes are populated. For the claimed-vs-verso comparison above it is irrelevant,
since verso has no machine column.

## Reproduce

The pinned wrapper/submodule SHAs per project, and the exact command behind every
committed artifact (extract, `plot_depgraph.py`, `blueprint_insights.py`, and the
`capture_verso_screenshots.py` verso shots), are in
[`../data/verso-comparison/README.md`](../data/verso-comparison/README.md). The
extract envelopes are not committed (they need a built Lean project); everything
else there is a seconds-long re-render from an extract.

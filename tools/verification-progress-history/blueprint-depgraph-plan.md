# Blueprint dependency-graph & summary reproduction plan

Goal: reproduce the dependency graphs and progress summaries that the
verso-blueprint projects (FLT, Carleson, Sphere-Packing, Noperthedron) publish,
from the data `probe-leanblueprint` already emits, and add three things the
native tools cannot: machine-confirmed colouring, a cross-project dashboard, and
a temporal (node-turned-green-over-time) view.

**Status (2026-07-31): Stages 0–3 implemented and validated; a Stage 5
(dependency-graph insights) added beyond the original scope.** `bp_graph.py`
(loader/model), `plot_depgraph.py` (DOT/SVG renderer), `blueprint_dashboard.py`
(cross-project index), and the `--archive-extracts` flag in `progress_history.py`
are in place; node counts match the `count_blueprint` oracle on all four `/tmp`
extracts (245/161/140/68), and the machine-verified vs claimed gap renders (e.g.
FLT 45% vs 54%, Carleson 90% vs 96%). Stage 4 (temporal graph) has its
prerequisite wired (Stage 0) but the history backfill is deferred
(compute/ops, version-floor-bounded). Six projects generated:
FLT/carleson/Sphere-Packing/Noperthedron + secure-messaging + KVAC.
124 tests green, ruff clean.

### Stage 5 — dependency-graph insights (added, not in original scope)

Triggered by comparing against a real verso-blueprint site
(leanprover.github.io/verso-blueprint's carleson Blueprint-Summary page), which
shows more than a burn-up: a closed/incomplete-deps/sorry/no-proof split, a
"most used in statements" ranking, and an entry index. `bp_graph.py` gained
`closure()`/`closure_summary()`/`downstream_counts()`/`in_degree()`/`ready_now()`;
`blueprint_insights.py` is the report CLI; `verso_manifest.py` reads a raw
`blueprint-manifest.json` for the one thing not in any extract at all.

**Validated, not guessed:** the "claimed" closure split is read directly off
`blueprint-proof-status` (no graph walk needed — `docs/SCHEMA.md` confirms
`proved`/`fully-proved` already encode probe-leanblueprint's own transitive
closure) and reproduces carleson's live page exactly: 154 closed / 6
incomplete-deps (±1 node of expected commit drift between our `/tmp` snapshot
and the live site). The independent "machine" cross-check is stricter: 140
closed on the same data, surfacing 14 theorems the blueprint calls fully closed
that actually rest on an axiom or an unclosed dependency once probe-lean's
per-node status is factored in through the same graph.

**Confirmed NOT reproducible, not merely assumed:** the Lemma/Theorem/
Proposition split some sites show. Checked exhaustively against every field on
every node across two real manifests (secure-messaging's 18 chapter manifests
and KVAC's current one) — `kind` is only ever `definition`/`theorem`, `title`
only ever prefixes `Definition`/`Theorem`. Not a probe-leanblueprint extraction
gap: the JSON graph model (`blueprint-manifest.json`) simply never carries this
distinction, on any project we've checked. Dropped from scope entirely.

**Missing informal coverage** (`warnings.leanOnlyNoStatement` in the raw
manifest) *is* recoverable, but probe-leanblueprint drops it when producing the
extract (confirmed against the full field list in `model.rs`) — so it needs
the raw manifest at the SAME commit as the extract, which only exists for KVAC
today (fresh, single file, commit-aligned). secure-messaging's manifest is
chapter-split across 18 files and has since drifted to a different commit than
its extract; FLT/carleson/Sphere-Packing/Noperthedron have no raw manifest left
on disk. `blueprint_insights.py` omits the section rather than reporting zero
when `--manifest` isn't given.

**A genuine finding, not a bug:** KVAC's blueprint has a real dependency cycle
(`attribute_lifting → single_attribute_mac → mucmz_mac_security →
attribute_lifting`, plus a nested 2-cycle) — traced by hand against the raw
edges before trusting the cycle-detector, confirmed real.

## Why this is feasible

The `probe-leanblueprint/extract` envelope is a normalized superset of what both
front-ends feed their own graph renderers. Per blueprint node it carries the
identity, the curated math edges, and both status axes:

| graph element | field |
|---|---|
| node id / label | `blueprint-label` |
| kind / title / chapter | `blueprint-kind`, `blueprint-title`, `blueprint-chapter`, `blueprint-group` |
| statement edges (solid) | `blueprint-statement-uses` |
| proof edges (dashed) | `blueprint-proof-uses` |
| statement state | `blueprint-statement-status` (`none < blocked < ready < formalized`) |
| proof state | `blueprint-proof-status` (`none < ready < proved < fully-proved`) |
| machine status | `verification-status` (per bound atom) |
| claimed-vs-derived | `blueprint-status-source` (`code-derived` / `declared`) |

The two status axes map one-to-one onto leanblueprint's colour legend; the
`*-uses` fields are the same statement/proof edge classes the native graphs
draw. Both Massot (LaTeX) and Verso front-ends collapse into this one schema, so
a single renderer covers all projects uniformly.

What is **not** reproducible: the typeset prose pages (statement/proof bodies,
cross-linked math). The extract keeps labels, titles, chapters and a discussion
field, not the rendered LaTeX/HTML body. We reproduce the navigational/status
layer (graph + dashboard), not the reading experience.

## Grounding: data on disk (2026-07-31)

Real single-commit `extract` + `summary` runs for all four Verso projects exist
in `/tmp` (ephemeral; regenerate with `probe-leanblueprint extract` if cleared):

| file | project | commit | keyed decls | blueprint nodes | thms | fully-proved | fraction |
|---|---|---|---|---|---|---|---|
| `/tmp/verso-flt.extract.json` + `sum_verso-flt.json` | FLT | ee47fd2a | 4228 | 245 | 194 | 105 | 0.54 |
| `/tmp/verso-carleson.extract.json` + `sum_verso-carleson.json` | Carleson | 8e93bee1 | 3337 | 161 | 161 | 154 | 0.96 |
| `/tmp/verso-sphere-packing.extract.json` | Sphere-Packing | 1828993f | 1512 | 140 | — | — | — |
| `/tmp/verso-noperthedron.extract.json` | Noperthedron | 83502054 | 1695 | 68 | — | — | — |

("blueprint nodes" = distinct `blueprint-label` count, matching the oracle and
the summary sidecar. FLT 245 / Carleson 161 also match. Counting keyed decls
with a non-null status instead overcounts: 246 / 211 / 167 / 117.)

Also present: Massot-path `/tmp/carleson.extract.json`, `/tmp/flt.extract.json`
(for front-end-independence and mismatch testing).

Three findings that shape the plan:

1. **Schema drift.** The `/tmp` runs are `schema-version` **2.0**; current
   probe-leanblueprint emits **3.0**. The 2.0 summary headline has only
   `theorems-total` / `theorems-fully-proved` / `fraction`; it lacks 3.0's
   `theorems-fully-proved-probe-lean-confirmed` and reports `mismatches: 0`.
   Treat schema-2.0 summary side fields as advisory (e.g. `totals.with-lean-decl`
   reads 0 for FLT despite bound nodes) — recompute all graph stats (nodes,
   bound, decl-missing, machine-verified) from the extract per-node data. The
   loader targets both schemas.
2. **Graph is a subset.** A node is one distinct `blueprint-label` (atoms grouped
   by label, atoms with a null label skipped), matching the `_collect_nodes`
   oracle — 245 nodes from 4228 keyed decls for FLT, because several decls share
   one label. Node identity is label-based, never key-based or
   statement-status-based. Edge targets are addressed as `probe:blueprint:«X»`
   (synthetic/planned) or `probe:X` (bound decl).
3. **Snapshots only.** One commit per project, so stages 1–3 build and validate
   on this data with no new compute; only stage 4 (temporal) needs new runs.

## Shared foundation: `bp_graph.py`

New module in `tools/verification-progress-history/`, sibling to
`blueprint_progress.py`. Turns one `extract` envelope into a normalized graph,
independent of front-end and schema.

```
Node:  one per distinct blueprint-label (skip atoms with a null label)
       id            = blueprint-label
       kind          = blueprint-kind    # last-write-wins across group; warn on conflict
       title         = blueprint-title   # last-write-wins across group
       chapter/group = blueprint-chapter / blueprint-group
       stmt_status   = blueprint-statement-status
       proof_status  = blueprint-proof-status
       bound         = any atom has language != "blueprint" OR blueprint-shadow
                       (NOT "code-path present" — matches _collect_nodes:167)
       verif         = rolled-up verification-status over the node's INCLUDED
                       real atoms only (language != "blueprint" AND _atom_included);
                       hidden / ignored / stub atoms must not sway status
       mismatch      = blueprint-status-mismatch (3.0) OR computed (2.0)
Edge:  src_label -> tgt_label, class in {statement, proof}
       1. collect *-uses from ALL atoms in the source label group
          (not one representative atom, else edges are silently lost)
       2. resolve each target: key -> target atom -> its blueprint-label
       3. drop intra-label (self) edges
       4. dedupe by (src_label, tgt_label, class)
       Count dropped targets BY REASON (missing key / key has no label /
       non-blueprint upstream / self-edge / duplicate), not a single tally.
```

Two rules, both already solved in the repo — reuse, do not reinvent:

- **Node selection** must match `blueprint_progress.py`'s `_collect_nodes`
  grouping (by `blueprint-label`, null labels skipped) so graph node counts
  equal the tested burn-up counter (the oracle). The oracle counts nodes, not
  edges — see Stage 1 for the separate edge-validation story.
- **Verification rollup** = the combined-atoms precedence from
  `plot_progress.py --atoms`: `failed > unverified > trusted > {verified,
  transitively-verified}`, over the node's included real atoms (above).
  Machine-verified = `verified ∪ transitively-verified`; `trusted`
  (axiom/external) dominates green. Trust detection is node-local (cross-node
  axiom reliance not caught; see the README "How to read the charts" caveat and
  open a tracking issue — this is NOT covered by #33 (failed red curve) or #34
  (untracked sorry debt)); state it in the header.

Loader accepts 2.0 and 3.0: core fields exist in both; 3.0-only fields
(`blueprint-decl-missing`, source-status, summary confirmed fields) read if
present, else derived.

### Terminology: three distinct "confirmed"s — do not conflate

A legend, a dashboard fraction, and the sidecar can all say "confirmed" while
meaning different things. Keep them separate and named:

- **machine-verified** — per-node `verif` rollup ∈ {verified, transitively-verified}.
  The graph's solid-green and the dashboard's machine-verified fraction.
- **binding-complete** (`thm_proved_confirmed`, `blueprint_progress.py:211`) —
  fully-proved AND bound AND no missing-decls AND no mismatch. A "not-refuted"
  bar, NOT affirmative verification.
- sidecar **`fraction-probe-lean-confirmed`** (3.0) — mirrors binding-complete,
  not the machine-verified rollup.

The graph uses machine-verified throughout; wherever earlier drafts said
"confirmed-green", read machine-verified.

## Colour mapping (the legend)

Node fill/border from `(stmt_status, proof_status, verif)`, matching
leanblueprint's legend plus the confirmed overlay. Bold rows are what the native
graphs cannot show.

| state | condition | native analog |
|---|---|---|
| not ready | stmt = blocked | `notready` (grey/dashed) |
| ready to formalize | stmt = ready | white, green border |
| statement formalized | stmt = formalized, proof < proved | blue |
| **proved (claimed)** | proof in {proved, fully-proved}, not machine-verified | green, hatched |
| **machine-verified** | proof = fully-proved AND verif ∈ {verified, transitively-verified} | solid green |
| **mismatch** | claims proved but verif ∈ {unverified, failed} | red outline |
| **trusted** | verif = trusted (axiom/external) | green + amber ring |

Evaluate in a single precedence order so overlapping states resolve
deterministically (first match wins):
`mismatch > failed > trusted > machine-verified > proved(claimed) >
statement-formalized > ready > not-ready`. Without this, one node can satisfy
several rows (e.g. `proof = fully-proved`, `verif = trusted`, `mismatch = true`).

## Stages

### Stage 0 — archive extracts (temporal enabler)

Only thing gating stage 4; land independently so history accrues.

- In `progress_history.py`, after `count_blueprint(env)` (~line 1307), copy the
  extract `path` to `data/<name>/extracts/<commit>.json.gz`. New
  `--archive-extracts` flag, default off; existing runs unaffected.
- Validation: a short-window run writes one archive per sample; `bp_graph.py`
  round-trips one.
- Effort: small. Risk: disk (~4.5 MB raw / sample; gzip).

### Stage 1 — faithful replica renderer

`plot_depgraph.py` (sibling to `plot_progress.py`) + shared `bp_graph.py`.

- Input: one `extract` envelope (start on `/tmp/verso-flt`, `/tmp/verso-carleson`).
- Emit Graphviz **DOT** always (dependency-free, portable); optionally shell to
  `dot -Tsvg` when present, mirroring `plot_progress.py`'s optional PNG. Layout
  is recognizably similar to native (both use `dot`), not pixel-matched.
- Header from the summary sidecar or recomputed: totals, fraction, per-chapter.
- Validation: **node** counts equal `count_blueprint` on the same envelope (the
  tested oracle counts nodes, not edges). **Edges** have no oracle — validate
  against small checked-in fixtures (shared labels, synthetic nodes, bound
  targets, missing targets, self-edges, duplicates, hidden atoms) plus the
  by-reason dropped-edge accounting from the Edge spec; `/tmp` snapshots are for
  exploration, not regression. Render all four Verso projects; confirm a Massot
  extract (`/tmp/carleson.extract.json`) yields the same model shape (front-end
  independence).
- Effort: medium. Risks: edge-target resolution (synthetic vs bound keys);
  leaf/orphan handling; chapter clustering via `blueprint-chapter`/`-group`.

### Stage 2 — confirmed vs claimed colouring

Delta on stage 1's colour function.

- Apply the mapping table's bold rows using the stage-1 `verif` rollup. Emit a
  `mismatches` list in the header and colour those nodes red.
- On this data: Verso extracts are `code-derived`, so claimed ≡ derived and
  mismatches are ~0; the signal lives in Massot projects (`\leanok` hand-toggled)
  and in `trusted` (axiom-reliant) nodes. Validate against
  `/tmp/carleson.extract.json` and a fixture with one flipped status.
- Effort: small on top of stage 1. Risk: node-local trust caveat (state it).

### Stage 3 — cross-project dashboard

- Run stages 1–2 per project into `data/<name>/depgraph.{dot,svg}` + a stats row.
- One static `index.html` linking each graph, with a comparison table keyed on
  **fractions, not raw counts** (node granularity differs across projects).
  Compute every fraction from the extract per-node data, not from schema-2.0
  summary side fields (advisory — see Grounding). Mind the three "confirmed"s
  (see Terminology): the dashboard's machine-verified fraction is the per-node
  `verif` rollup, which is NOT the sidecar's `fraction-probe-lean-confirmed`
  (a not-refuted bar). Label the column for whichever metric it actually shows.
- Validation: table matches each project's recomputed headline; four projects
  render side by side.
- Effort: small–medium.

### Stage 4 — temporal graph

Heaviest; only stage needing new compute.

- Prereq: stage 0 archival running + per-project configs in `progress_history.py`
  for flt/carleson/sphere-packing/noperthedron. The per-sample probe-lean
  selection and `--dep-cache-dir` machinery already exist from the
  secure-messaging work.
- Build: diff consecutive archived extracts by `blueprint-label`; annotate each
  node with the commit it first reached machine-verified; render a slider /
  small-multiples "green over time". Reuses the existing per-commit walk.
  Caveat: this is a label-continuity view, not semantic theorem identity —
  label renames / splits / merges / front-end migrations appear as delete +
  new-node events. Add a rename/alias map or state the limitation.
- Reality check: FLT and Carleson are large; full-history backfill is expensive
  and bounded by the Lean/probe version floors (see
  `probe-lean-version-constraints`; precedent in the dalek-lean backfill where
  pre-floor commits were unreachable). Scope as "archive from now forward,
  backfill opportunistically over the reproducible window," not "reconstruct full
  history."
- Effort: large (mostly compute/ops). Risks: version-floor unreachable ranges;
  per-project render-command quirks (secure-messaging needed
  `--verso-render-cmd scripts/render-docs-site.sh`).

## Sequencing

Stage 0 runs in parallel with stage 1 (independent). Stages 1 → 2 → 3 are a
tight chain on existing `/tmp` data with no new compute, deliverable quickly.
Stage 4 waits on stage 0 baking plus a compute-budget decision.

## Open decisions

1. **Re-extract at 3.0, or schema-tolerant loader on the `/tmp` 2.0 data now?**
   Recommendation: schema-tolerant loader + `/tmp` data for stages 1–3 (fast,
   free); re-extract only if the 3.0 mismatch/confirmed fields prove necessary.
2. **Layout dependency:** emit DOT always and shell to `dot` when available
   (recommended), or a pure-Python layered layout to stay fully dependency-free.
3. **Location:** extend `verification-progress-history/` (recommended — reuse
   `bp_graph`/`colors`/counters, one source of truth) vs a new `blueprint-depgraph/`
   tool.

## Conventions

Open a GitHub issue before any PR; PRs as drafts (project convention).

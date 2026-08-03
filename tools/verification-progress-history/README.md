# verification-progress-history

Reconstructs a verification project's progress over its git history as a
burn-up time series. The tool samples one commit per period, re-runs the real
verifier at each commit, and writes per-commit metrics to JSONL and CSV.
`plot_progress.py` renders these as a burn-up SVG.

The metric set depends on the pipeline. Verus and Aeneas record the colour set
(`tracked`, `verified`, `verified+trusted`, `translated`). The `leanblueprint`
pipeline records a two-axis blueprint set (`formalized`, `proved`). The `lean`
pipeline, for a Lean project with no blueprint, records a kind-split sorry set
(`without sorry`, `trust boundary`, per definition and theorem).

This is a standalone Python 3.10+ CLI with no runtime dependencies beyond the
standard library. It is not a GitHub Action: a multi-hour history walk with
per-commit toolchain installs does not suit CI.

Colour metric definitions live in the VeriLib docs,
[Atom statuses and colours](https://beneficial-ai-foundation.github.io/VeriLib-Docs/components/processor/atom-statuses-and-colours/).
Reproduce them from any extract JSON with `colors.py <extract.json> --table`.
The blueprint two-axis definitions live in probe-leanblueprint's
`docs/SCHEMA.md`; reproduce them with `blueprint_progress.py <extract.json>
--table`. The `lean` kind-split counts come straight from probe-lean's
`verification-status`; reproduce them with `lean_progress.py <extract.json>
--table`.

## Files

| File | Purpose |
|------|---------|
| `progress_history.py` | Sample history, checkout, run extract, write JSONL/CSV. |
| `colors.py` | Compute the colour metric record (Verus/Aeneas) from one extract JSON. |
| `blueprint_progress.py` | Compute the two-axis blueprint metric record (leanblueprint) from one extract JSON. |
| `lean_progress.py` | Compute the kind-split sorry metric record (plain `lean`) from one extract JSON. |
| `plot_progress.py` | Render the burn-up chart (SVG, optional PNG). |
| `bp_graph.py` | Build the blueprint dependency-graph model (nodes/edges/state/closure) from one extract JSON. |
| `plot_depgraph.py` | Render that graph as Graphviz DOT (optional SVG/PNG via `dot`). |
| `blueprint_dashboard.py` | Cross-project static `index.html` comparing several extracts. |
| `blueprint_insights.py` | Closure split, most-used ranking, entry index, informal-coverage report. |
| `report_style.py` | Shared palette and CSS tokens for the HTML reports. |
| `verso_manifest.py` | Read per-node `warnings` (e.g. missing informal coverage) from a raw Verso manifest. |
| `data/<name>/` | Committed outputs: `progress.{jsonl,csv}`, `burnup*.{svg,png}`; `extracts/<commit>.json.gz` when `--archive-extracts`. |

## Requirements

- Python 3.10+ and `git`.
- The probe for your pipeline on `PATH`, pinned to one version for the whole run:
  - Verus: [`probe-verus`](https://github.com/Beneficial-AI-Foundation/probe-verus) (installs verus-analyzer, scip, and the matching Verus).
  - Aeneas: [`probe-aeneas`](https://github.com/Beneficial-AI-Foundation/probe-aeneas) plus `elan` (runs Charon and `lake build`).
  - Lean blueprint: [`probe-leanblueprint`](https://github.com/Beneficial-AI-Foundation/probe-leanblueprint) plus `probe-lean` and `elan` (runs `probe-lean extract` and renders the Verso blueprint with `lake exe vbp build`).
  - Lean (no blueprint): [`probe-lean`](https://github.com/Beneficial-AI-Foundation/probe-lean) plus `elan` (runs `probe-lean extract`). Same per-Lean-version binary layout as the blueprint pipeline.

## Run

One repo at a time. Each sample re-verifies the project, so runs are long.
Start with `--dry-run` to list the sampled commits, then drop it. Re-invoke
with `--resume` to continue, and `--retry-failed` to redo any sample that
didn't finish `ok`. Output defaults to `data/<name>/progress.jsonl` (and
`.csv`).

### dalek-verus (Verus)

```bash
python3 progress_history.py /path/to/dalek-verus \
  --pipeline verus --project-subdir curve25519-dalek --package curve25519-dalek \
  --since 2025-07-14 --work-clone /tmp/vph-dalek-verus \
  --sample-timeout 7200 --resume
```

### SparsePostQuantumRatchet-verify (Aeneas)

```bash
python3 progress_history.py /path/to/SparsePostQuantumRatchet-verify \
  --pipeline aeneas --since 2026-03-13 --work-clone /tmp/vph-spqr \
  --sample-timeout 3600 --resume
```

### curve25519-dalek-lean-verify (Aeneas)

```bash
python3 progress_history.py /path/to/curve25519-dalek-lean-verify \
  --pipeline aeneas --since 2026-03-11 --cadence monthly \
  --work-clone /tmp/vph-dalek-lean --sample-timeout 3600 --resume
```

`--since 2026-03-11` is the earliest reproducible commit. probe-lean needs
Lean >= v4.28.0-rc1 (reached 2026-02-23), and `probe-aeneas extract` needs
`aeneas-config.yml`, added 2026-03-11.

### secure-messaging (Lean blueprint)

```bash
python3 progress_history.py /path/to/secure-messaging \
  --pipeline leanblueprint --branch origin/main --since 2026-06-03 \
  --cadence monthly --work-clone /tmp/vph-sm --sample-timeout 14400 --resume \
  --verso-render-cmd 'BLUEPRINT_PROGRESS_HISTORY_SEED=0 scripts/render-docs-site.sh' \
  --dep-cache-dir /tmp/vph-dep-cache
```

The `versoBlueprint` dependency was added on 2026-06-03, but the graph
manifest only renders reliably from 2026-06-24 onward. The three samples in
between record `extract_failed`: probe-lean runs fine, but there's no
blueprint graph yet to enrich. `--branch origin/main` is needed because the
sampled repo's default checkout can be a feature branch. This pipeline
records the two-axis blueprint metric set (see Output), not the colour set;
it's auto-detected from a `versoBlueprint` lakefile or a `blueprint/src/web.tex`
tree.

secure-messaging needs `--verso-render-cmd` because it renders its docs per
chapter with its own `scripts/render-docs-site.sh`, not the default `lake exe
vbp build` (which fails there with "could not find a blueprint-gen
executable"). `SEED=0` skips the script's `gh`-based history seeding. Any
render command that leaves `blueprint-manifest.json` file(s) somewhere under
`<blueprint-root>/_out/site` works, since probe-leanblueprint merges them.

**probe-lean is Lean-version-specific.** Each sample runs the
`probe-lean-v<toolchain>` matching that commit's `lean-toolchain`, selected
from `--probe-lean-dir` (default: the directory of `probe-lean` on `PATH`). A
missing version records a clean `setup_failed`. A run can span a toolchain
change (here v4.29 to v4.30), and each change forces a full dependency
rebuild, which is slow for secure-messaging since VCVio has no prebuilt cache.
Sample coarsely first if you're crossing a toolchain boundary.

`--dep-cache-dir` makes that rebuild a one-time cost. After the first
successful sample, it snapshots the compiled dependency build keyed by Lean
toolchain and lake manifest, and restores it in seconds on any later sample
with the same key instead of recompiling. It trades disk (about 8 GB per key
for secure-messaging, mostly Mathlib) for time, and is safe to delete anytime.
Point it at a persistent location to make reruns, `--retry-failed`, and finer
cadences essentially free on the build side.

### KeyedVerificationAnonymousCredential-model (Lean, no blueprint)

```bash
python3 progress_history.py /path/to/KeyedVerificationAnonymousCredential-model \
  --pipeline lean --cadence monthly --work-clone /tmp/vph-kvac \
  --sample-timeout 3600 --resume --dep-cache-dir /tmp/vph-dep-cache
```

KVAC-model has a blueprint, but it's written entirely as informal previews
with no graph nodes, so the `leanblueprint` pipeline binds 0 nodes and charts
nothing. The `lean` pipeline sidesteps the blueprint and counts probe-lean's
declarations directly. It records the kind-split sorry set (see Output), and
is the fallback for any Lean project without an informative blueprint
(auto-detected when there is a `lean-toolchain`/lakefile but no
`versoBlueprint` dependency or Massot `blueprint/src/web.tex`).

It shares the same probe-lean and `--dep-cache-dir` mechanics as
`leanblueprint` above, just without a Verso render step. The committed
`data/KeyedVerificationAnonymousCredential-model/` capture is 4 monthly
samples over `experiment/bump-v4.30.0`, spanning the v4.28.0 to v4.30.0
toolchain bump. Declarations grow from 9 to 174 with 0 sorries or axioms
throughout.

Add `--install-probe-lean` to auto-fetch a missing `probe-lean-v<ver>` via the
installer instead of recording `setup_failed` (the Lean analogue of
`probe-verus setup`, shared with the `leanblueprint` pipeline). It's off by
default because it runs a network installer; `--probe-lean-install-cmd`
overrides the command, e.g. to point at a vetted local `install.sh`. The
official installer writes to `~/.local/bin`, so `--probe-lean-dir` must
resolve there.

**Caveat.** The built-in default fetches `install.sh` from probe-lean's
mutable `main` branch and pipes it to `bash`. For a reproducible or
supply-chain-sensitive run, override `--probe-lean-install-cmd` to pin a tag
or commit, or point at a vetted local `install.sh`, rather than relying on
whatever `main` holds at run time.

### A single commit

To resample one commit and update its row, pass `--commit` (repeatable)
instead of a date range. It runs those commits and upserts them by SHA,
leaving the rest of the series untouched. Useful for filling in a new HEAD or
redoing a commit that failed.

```bash
python3 progress_history.py /path/to/dalek-verus \
  --pipeline verus --project-subdir curve25519-dalek --package curve25519-dalek \
  --commit HEAD --work-clone /tmp/vph-dalek-verus
```

Other options: `--cadence {weekly,biweekly,monthly}` (or `--cadence-weeks N`),
`--anchor-day`, `--branch`, `--until`, `--output`/`--csv`, `--smt-seed`,
`--skip-verify`, `--install-probe-lean`/`--probe-lean-install-cmd`. Run
`--help` for the full list.

## Plot

```bash
python3 plot_progress.py data/dalek-verus/progress.jsonl --png
```

Plots only `ok` samples; gaps are noted in the caption. `--in-progress` adds
the yellow curve and `--unspecified` adds white. `--png` also writes a PNG
(via rsvg-convert, inkscape, or imagemagick), and `--png-scale` sets the
raster scale (default 2.0). See "How to read the charts" below for what each
curve means.

For a **leanblueprint** history the mode is auto-detected from the records
and two stacked panels are drawn instead, one for Definitions and one for
Theorems. `--in-progress`/`--unspecified` are colour-pipeline options and are
ignored here.

For a **lean** history (no blueprint) the same two panels are drawn, but with
no fixed ceiling: `total` is the declaration count, which grows over time.
`--in-progress`/`--unspecified` are ignored here too.

```bash
python3 plot_progress.py data/secure-messaging/progress.jsonl --combined --unspecified --png
```

`--combined` (leanblueprint or lean) draws a single combined panel instead,
pooling definitions and theorems into one blueprint-node or declaration unit.
It uses the FC ("Atom statuses and colours") vocabulary described below. The
ceiling is a per-sample inventory that can go down as well as up, so this is
not a strictly monotonic burn-up. Writes `burnup-combined.svg` and never
overwrites the two-panel `burnup.svg`. `--combined` refuses to plot a history
that predates the per-node columns, rather than rendering them as zero.
`--strict` exits non-zero if any sample violates the frontier nesting; the
warning is stamped into the SVG regardless. See `combined-atoms-plan.md` for
the full derivation.

```bash
python3 plot_progress.py \
  data/KeyedVerificationAnonymousCredential-model/progress.jsonl --combined --png
```

On the committed KVAC capture, every declaration is `transitively-verified`
with 0 sorries, trusted atoms, or failures, so the three frontiers coincide
and the green line tracks the ceiling as it grows from 9 to 174.

**Scope caveat (leanblueprint only).** The leanblueprint combined chart
measures blueprint completion, not repo-wide sorry debt. `in-progress` only
counts formalized blueprint nodes whose bindings contain a sorry; a sorry in a
declaration the blueprint doesn't track is invisible here. So
`in-progress = 0` means every formalized blueprint node is sorry-free, not
that the repo has no sorries. Surfacing untracked sorry debt is tracked in
[#34](https://github.com/Beneficial-AI-Foundation/veritooling/issues/34). The
lean combined chart has no such blind spot: it counts every declaration, so
its `in-progress` is the project's full sorry count.

## Dependency graph & cross-project dashboard

Where the burn-up plots the history of the scalar counts, `plot_depgraph.py`
renders the blueprint dependency graph for a single extract, and
`blueprint_dashboard.py` compares several projects on one page. Both read the
same `probe-leanblueprint/extract` envelope and recompute everything from its
per-node data, never from a summary sidecar.

To get that envelope for a one-off look at a project you're not sampling
through `progress_history.py` (which archives one via `--archive-extracts`
instead, see below), run `probe-leanblueprint extract` directly against a
clone with its dependencies already built:

```bash
cd /path/to/the/lean/project   # `.lake/build` should already have .olean files
probe-leanblueprint extract . --no-render -o /tmp/myproject.extract.json
```

`--no-render` skips re-rendering the Verso docs site and just reads the
`blueprint-manifest.json` already under `docs/_out/site`; it fails if there
isn't one (drop the flag, or pass `--verso-render-cmd`, to render fresh
instead). Without a prebuilt `.lake/build`, this also runs a full `lake
build` first, which is why extracting a Mathlib-scale project like FLT,
Carleson, Sphere-Packing, or Noperthedron ad hoc is slow.

```bash
# One project -> Graphviz DOT (stdout), or SVG/PNG if `dot` is on PATH.
python3 plot_depgraph.py /tmp/verso-carleson.extract.json -o carleson.svg

# Several projects -> data/<...>/index.html + one graph, and one
# blueprint_insights.py --html report, per project.
python3 blueprint_dashboard.py /tmp/verso-*.extract.json -o site/
```

Node grouping is by `blueprint-label`, one node per label, identical to
`blueprint_progress.py`'s counter; a test cross-checks the node count. Solid
edges are statement `\uses`; dashed edges are proof `\uses`/`\proves`.

The colouring adds two things the native leanblueprint and Verso graphs can't
show:

- **machine-verified** (solid green): probe-lean's own `verification-status`
  rollup lands on `verified` (no sorry, axiom, or failure in the node's
  bindings), rather than a hand-toggled `\leanok`.
- **mismatch** (red outline): a node the blueprint claims proved but the
  machine refutes. Verso blueprints are code-derived, so mismatches there are
  close to zero; the signal appears on Massot (`\leanok`-driven) blueprints.

The dashboard table is keyed on fractions, not raw counts, since node
granularity differs across projects. It shows **claimed** (the blueprint's
`fully-proved` claim) beside **machine-verified** (the stricter probe-lean
rollup); these are distinct from each other and from the sidecar's
`fraction-probe-lean-confirmed`, a "not-refuted" bar. Trust detection is
node-local: cross-node axiom reliance is not caught.

To feed these from history rather than a one-off extract, run the sampler
with `--archive-extracts`. Each `ok` sample's envelope is gzipped to
`data/<name>/extracts/<commit>.json.gz`, the substrate for a per-commit or
temporal graph.

## Dependency-graph insights

`node_state` above is node-local: a node's own bindings can be
machine-verified while something it depends on isn't, and the colour alone
doesn't show that. `blueprint_insights.py` answers the graph-wide question the
verso-blueprint "Blueprint Summary" pages ask: closed versus
blocked-by-a-dependency, a most-used ranking, and an entry index. Everything
is recomputed from `bp_graph`, not copied from any site.

```bash
python3 blueprint_insights.py /tmp/verso-carleson.extract.json --table
python3 blueprint_insights.py /tmp/verso-carleson.extract.json --html -o carleson.insights.html
```

`--html` writes a standalone page (stat tiles, a claimed/machine stacked bar
for the four-way split, the actionable chip list, both most-used tables, and a
collapsible entry index) instead of the plain-text table: same data, easier
to scan. It shares its palette and CSS tokens (`report_style.py`) with
`blueprint_dashboard.py`'s cross-project page, so the two read as one system.

The closed/incomplete/sorry/no-proof split is computed twice:

- **claimed**: read straight off `blueprint-proof-status`. Per
  `probe-leanblueprint`'s schema, `proved` already means the proof is
  sorry-free on its own, and `fully-proved` already means the node and
  everything it depends on are done, so no graph walk is needed. Validated
  against carleson's live Blueprint-Summary page, matching within one node of
  expected commit drift.
- **machine**: an independent cross-check, a graph walk over the same
  `\uses` edges gated on probe-lean's own per-node status rather than the
  blueprint's bookkeeping. On carleson this is stricter (140 closed rather
  than 154): some theorems the blueprint calls fully closed rest on an axiom
  or an unclosed dependency once probe-lean is factored in.

Also reported: **actionable** entries (statement `ready` with every
dependency already formalized, our own reading of "the next step is
unblocked"; deliberately not called "ready now", since that name is a
stricter, different metric on the live verso-blueprint site), **most used in
statements** and **most used in proofs** (two separate rankings, each by that
column's own direct-use count, matching how the live page splits them rather
than one list by downstream unlocks), and a full **entry index**. A
dependency cycle, a data-quality issue not expected in a DAG, is flagged
rather than silently mis-closed; KeyedVerificationAnonymousCredential-model's
blueprint has one.

**What this can't show.** The Lemma/Theorem/Proposition split some sites
display isn't in the JSON graph model on any project we checked; `kind` is
only ever `definition` or `theorem`. **Missing informal coverage** (a
Lean-bound entry with no natural-language write-up) is recoverable, but only
from a raw `blueprint-manifest.json` at the same commit as the extract. Pass
one or more chapter manifests via `--manifest` (`verso_manifest.py` merges
them by label); without it, this section is simply omitted, not reported as
zero.

## How to read the charts

All charts share one vocabulary, **tracked** (the ceiling), **verified+trusted**,
**verified**, **in-progress**, **unspecified**, **failed**, from the VeriLib
"Atom statuses and colours" (FC) model. What differs is the unit being
counted, stated on each chart's y-axis and subtitle. Read a chart as nested
frontiers, where each larger band contains the smaller ones, plus zero-based
status counts drawn only when they occur.

**Colour burn-up** (`burnup.svg`, Verus/Aeneas, unit: a Rust `exec` atom).
- **tracked (ceiling)**: atoms in scope (`exec_total` minus grey/disabled).
- **verified+trusted**: proved (green) plus axiom/trusted (purple). The
  completion frontier.
- **verified**: proved with no trust reliance (green).
- **in-progress** (`--in-progress`): yellow, an incomplete proof (sorry or
  assume).
- **unspecified** (`--unspecified`): white, tracked but no spec written yet.
- **failed**: red, a failed verification. Drawn only when some sample has
  one, like `translated`; its absence means nothing failed.
- **translated**: Aeneas-only intermediate.

The gap between `tracked` and `verified+trusted` is white plus yellow plus
red. Don't read it as the sorry count on its own; `--in-progress` and
`--unspecified` split out white and yellow, and red draws itself when
present.

**Blueprint two-panel** (`burnup.svg`, leanblueprint, unit: a blueprint node,
split into Definitions and Theorems panels).
- **total**: every node of that kind (bound, planned, or over-claimed).
- **formalized**: the Lean statement or signature exists (the blueprint
  statement axis).
- **proved** (theorems only): sorry-free and probe-lean-confirmed.

**Lean two-panel** (`burnup.svg`, lean, unit: a Lean declaration, split into
Definitions and Theorems panels, no fixed ceiling since `total` grows over
time).
- **total**: every declaration of that kind.
- **without sorry**: `verified + transitively-verified + trusted`.
- **trust boundary**: `transitively-verified + trusted`, sound modulo the
  axioms and external trust base.
- **failed**: an elaboration error, drawn as its own curve only when present.

The gap between `total` and `without sorry` is sorry plus failed, plus any
unrecognised or absent status (`lean_progress.py` warns about those). The gap
between `without sorry` and `trust boundary` is the set that is locally clean
but transitively contaminated.

**Combined** (`burnup-combined.svg`, leanblueprint `--combined`, unit: a
blueprint node, definitions and theorems pooled). Same FC bands as the colour
burn-up, but the statement axis comes from the blueprint and the proof status
from probe-lean's own per-atom `verification-status`, rolled up per node by
worst status, matching `colors.py` so the chart stays consistent with the
colour burn-up.
- **tracked (ceiling)**: all nodes. A per-sample inventory that may rise or
  fall.
- **verified+trusted**: formalized nodes whose bound atoms are all clean,
  including trusted (axiom/external).
- **verified**: the subset with no trusted binding (green: probe-lean
  `verified` + `transitively-verified`).
- **in-progress**: formalized nodes with a sorry in a binding, drawn when
  present.
- **failed**: formalized nodes with an elaboration error, drawn when present.
- **unrealized**: formalized nodes with no bound atom carrying a machine
  status, an over-claim or shadow binding, drawn when present.
- **unspecified** (`--unspecified`): nodes with no Lean statement yet.

These zero-based curves are drawn only when present, so a clean history stays
uncluttered. Because the unit is a node, sorries in code the blueprint doesn't
track are not shown (see the Scope caveat above).

**Combined** (`burnup-combined.svg`, lean `--combined`, unit: a Lean
declaration, definitions and theorems pooled). Same FC bands, but both axes
come from probe-lean since there's no blueprint, so it sees every
declaration.
- **tracked (ceiling)**: all declarations. Grows over time, no fixed ceiling.
- **verified+trusted**: `verified + transitively-verified + trusted` (the
  two-panel "without sorry").
- **verified**: `verified + transitively-verified` (green, no trusted).
- **in-progress**: declarations with a sorry (`unverified`), drawn when
  present. This is the project's full sorry count, not just tracked nodes.
- **failed**: declarations with an elaboration error, drawn when present.
- **unspecified** and **unrealized**: not applicable to lean, never drawn.

## Scheduling weekly updates (cron)

`--resume` makes the tool incremental and safe to run unattended. It fetches
new commits into the reused `--work-clone`, samples only commits not already
recorded (upserting by SHA), and leaves the file untouched on a week with no
new commit. `--fail-on-error` exits non-zero if any sample processed this run
isn't `ok` (skipped or already-recorded samples don't count), so a wrapper's
`set -e` surfaces a broken week to cron mail or a log monitor.

`cron/` has a ready-to-edit setup:

- `cron/update-progress.sh`: copy per project, edit the CONFIG block,
  `chmod +x`. It runs the sample (`--resume --fail-on-error`), regenerates the
  chart, and commits the data if it changed. Run it once by hand first.
- `cron/example.crontab`: a Wednesday 07:00 schedule, so the newest sample is
  fresh for a Thursday review (the default `--anchor-day` is `wednesday`).

The wrapper handles the cron gotchas: a minimal `PATH`/`HOME` (the probe and
toolchain must resolve for the cron user), overlap via `flock`, and
publishing the result. The tool only writes files; the wrapper does the `git
add`/`commit`/`push`, to a bot data branch by default (adapt that step to
your workflow).

## Output

One JSON object per sampled commit, upserted by commit so `--retry-failed`
replaces a row rather than duplicating it; the CSV mirrors it. Columns:

`repo, pipeline, sample_date, commit, commit_date, tool, tool_version, status,
reason, commit_validated, duration_sec, grey, white, red, yellow, light_green,
dark_green, purple, exec_total, dot_red, dot_yellow, dot_green, art_total,
tracked, verified, verified_trusted, translated`

The `leanblueprint` pipeline fills a separate two-axis set instead (the
colour columns above stay blank, as `translated` does for non-Aeneas):

`bp_nodes_total, bp_nodes_bound, bp_nodes_planned, bp_nodes_decl_missing,
bp_def_total, bp_def_formalized, bp_thm_total, bp_thm_formalized, bp_thm_proved,
bp_thm_proved_confirmed`

and, for the `--combined` chart, a per-kind probe-lean proof-status partition
over the formalized nodes:

`bp_def_verified, bp_def_trusted, bp_def_in_progress, bp_def_failed,
bp_def_unrealized` (and the `bp_thm_*` counterparts)

The `lean` pipeline fills its own kind-split set instead (the colour and
`bp_*` columns stay blank), one group per kind:

`lean_def_total, lean_def_sorry, lean_def_verified, lean_def_trans_verified,
lean_def_trusted, lean_def_failed` (and the same six with a `lean_thm_`
prefix)

These are the raw per-kind `verification-status` tallies. `sorry` means
`unverified`, the declaration's own body has a sorry. `verified` means
locally sorry-free but a transitive dependency is not. `trans_verified` means
clean all the way to the trust base. `trusted` means axiom,
`@[externally_verified]`, or `*External.lean`. `failed` means an elaboration
error. An `axiom` is bucketed with theorems. The plot derives `without sorry`
and the `trust boundary` from these (see Plot).

A blueprint node has two axes (see probe-leanblueprint's `docs/SCHEMA.md`):
statement (`formalized` means the Lean statement or signature exists) and
proof (`fully-proved` means sorry-free). `bp_*_formalized` counts
statement-formalized nodes; `bp_thm_proved` counts the blueprint's
`fully-proved` claim, and `bp_thm_proved_confirmed` counts the
probe-lean-confirmed subset: bound, whole binding present, not contradicted
by probe-lean. This matches probe-leanblueprint's own
`theorems-fully-proved-probe-lean-confirmed` headline. `bp_nodes_*` splits
every node into bound (has a declaration), planned-only (a pure stub), and
decl-missing (an over-claim). The
`bp_*_{verified,trusted,in_progress,failed,unrealized}` set partitions the
formalized nodes by the probe-lean status rolled up from their bound atoms,
worst status wins. `unrealized` means formalized but no bound atom carries a
machine status, an over-claim or shadow binding. Per kind they sum to
`bp_*_formalized`.

`status` is one of `ok`, `setup_failed`, `checkout_failed`, `extract_failed`,
`verify_error`, `timeout`, `commit_mismatch`. Only `ok` samples are charted.
`verify_error` marks a commit that produced no per-function statuses (for
leanblueprint, a render yielding 0 blueprint nodes; for lean, an extract with
0 declarations), a visible gap rather than a real "0 verified" point.

## How it works

Clone once into `--work-clone`, never your own checkout. Bucket commits by
period, keep the latest in each, and always include HEAD. Oldest to newest:
`git checkout -f`, run the extract, then read the freshly written JSON and
confirm its `source.commit` matches the sample before recording. Verus
installs the matching release per commit; Aeneas, lean, and leanblueprint
clean and refetch the Lean build when `lean-toolchain` changes. leanblueprint
also drops the previous sample's Verso render (`_out/site`) each commit,
since the tool reuses an existing render and `source.commit` is git-derived,
so the commit-match guard wouldn't catch a stale one; the lean pipeline has
no render step. With `--dep-cache-dir`, lean and leanblueprint restore the
compiled dependency build, keyed by toolchain and manifest, instead of
recompiling on a toolchain change or fresh clone. Failures are recorded with
a reason, not dropped.

## Tests

```bash
pip install ruff pytest
ruff format --check tools/ && ruff check tools/
pytest tools/verification-progress-history/tests -q
```

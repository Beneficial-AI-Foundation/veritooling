# verification-progress-history

Reconstructs a verification project's progress over its git history as a burn-up
time series. The tool samples one commit per period, re-runs the real verifier
at each commit, and writes per-commit metrics to JSONL and CSV. `plot_progress.py`
renders those as a burn-up chart.

The metric set depends on the pipeline. Verus and Aeneas record the colour set
(`tracked`, `verified`, `verified+trusted`, `translated`). The `leanblueprint`
pipeline records a two-axis blueprint set (`formalized`, `proved`). The `lean`
pipeline, for a Lean project with no blueprint, records a kind-split sorry set
(`without sorry`, `trust boundary`, per definition and theorem).

Standalone Python 3.10+, standard library only. A full run is a multi-hour
history walk that installs a toolchain per sampled commit.

## Which script do I need?

The scripts here serve two distinct jobs. Pick the guide for yours. Each is a
runnable walkthrough against the committed `data/`.

| I want to… | Run this chain | Guide |
|------------|----------------|-------|
| Progress **over git history** as a burn-up time series | `progress_history.py` then `plot_progress.py` | [guides/history-burnup.md](guides/history-burnup.md) |
| **One snapshot's** blueprint dependency graph, closure/insights, or a cross-project comparison | `bp_graph.py` then `plot_depgraph.py` / `blueprint_insights.py` / `blueprint_dashboard.py` | [guides/graph-and-dashboard.md](guides/graph-and-dashboard.md) |
| **How accurate** our reproduction is against verso-blueprint's own pages | (the same chain, compared to verso's four reference blueprints) | [guides/verso-blueprint-comparison.md](guides/verso-blueprint-comparison.md) |

`data/README.md` maps every committed `data/<project>/` back to the exact
command that produced it. `leanblueprint-metrics.md` explains how the
leanblueprint numbers are computed.

## Files

| File | Purpose |
|------|---------|
| `progress_history.py` | Sample history, checkout, run extract, write JSONL/CSV. |
| `colors.py` | Colour metric record (Verus/Aeneas) from one extract JSON. |
| `blueprint_progress.py` | Two-axis blueprint metric record (leanblueprint) from one extract JSON. |
| `lean_progress.py` | Kind-split sorry metric record (plain `lean`) from one extract JSON. |
| `plot_progress.py` | Render the burn-up chart (SVG, optional PNG). |
| `persist_progress_jsonl.py` | Write `ok` samples into VeriLib `repostats` (meaning-based fields). |
| `repos.map.json` | Project → `{dev,staging,prod}` VeriLib `repo_id` map. |
| `bp_graph.py` | Build the blueprint dependency-graph model from one extract JSON. |
| `plot_depgraph.py` | Render that graph as Graphviz DOT (SVG/PNG when `dot` is present). |
| `blueprint_insights.py` | Closure split, most-used ranking, entry index, informal-coverage. |
| `blueprint_dashboard.py` | Cross-project static `index.html` over several extracts. |
| `report_style.py` | Shared palette and CSS tokens for the HTML reports. |
| `verso_manifest.py` | Read per-node warnings (e.g. missing informal coverage) from a raw Verso manifest. |
| `data/<name>/` | Committed outputs (see `data/README.md`). |

The three metric modules each print their own table for one extract JSON, which
is where the committed columns are defined: `colors.py <extract.json> --table`,
`blueprint_progress.py <extract.json> --table`, `lean_progress.py <extract.json>
--table`. Colour definitions also live in the VeriLib docs,
[Atom statuses and colours](https://beneficial-ai-foundation.github.io/VeriLib-Docs/components/processor/atom-statuses-and-colours/);
the blueprint two-axis definitions live in probe-leanblueprint's `docs/SCHEMA.md`.

## Requirements

Python 3.10+, `git`, and the probe for your pipeline on `PATH`, pinned to one
version for the whole run:

- Verus: [`probe-verus`](https://github.com/Beneficial-AI-Foundation/probe-verus) (installs verus-analyzer, scip, and the matching Verus).
- Aeneas: [`probe-aeneas`](https://github.com/Beneficial-AI-Foundation/probe-aeneas) plus `elan` (runs Charon and `lake build`).
- Lean blueprint: [`probe-leanblueprint`](https://github.com/Beneficial-AI-Foundation/probe-leanblueprint) plus `probe-lean` and `elan`.
- Lean, no blueprint: [`probe-lean`](https://github.com/Beneficial-AI-Foundation/probe-lean) plus `elan`.

probe-lean is Lean-version-specific: each sample runs the `probe-lean-v<toolchain>`
matching that commit's `lean-toolchain`, selected from `--probe-lean-dir` (default:
the directory of `probe-lean` on `PATH`). A missing version records a clean
`setup_failed`. `--install-probe-lean` auto-fetches a missing one via the
installer; it is off by default because it runs a network installer. See the
[history guide](guides/history-burnup.md) for the supply-chain caveat.

## Run

One repo at a time; each sample re-verifies the project, so runs are long. The
[history guide](guides/history-burnup.md) is the walkthrough; `data/README.md`
lists the exact command behind each committed series. A representative run:

```bash
python3 progress_history.py /path/to/dalek-verus \
  --pipeline verus --project-subdir curve25519-dalek --package curve25519-dalek \
  --since 2025-07-14 --work-clone /tmp/vph-dalek-verus \
  --sample-timeout 7200 --resume
```

Start with `--dry-run` to list the sampled commits. `--resume` continues an
interrupted run and skips commits already recorded; `--retry-failed` redoes any
sample that did not finish `ok`. To resample one commit and upsert its row, pass
`--commit` (repeatable) instead of a date range.

For lean and leanblueprint runs, `--dep-cache-dir` snapshots the compiled
dependency build keyed by toolchain and lake manifest, then restores it in
seconds on later samples instead of recompiling. It trades disk (about 8 GB per
key for a Mathlib-scale project) for time and is safe to delete anytime. Point
it at a persistent location to make reruns and finer cadences nearly free on the
build side. A run that crosses a toolchain change forces a full rebuild per
change, so sample coarsely first across a boundary.

Other options: `--cadence {weekly,biweekly,monthly}` (or `--cadence-weeks N`),
`--anchor-day`, `--branch`, `--since`/`--until`, `--output`/`--csv`,
`--smt-seed`, `--skip-verify`, `--verso-render-cmd`, `--archive-extracts`,
`--probe-lean-install-cmd`. Run `--help` for the full list, and the history
guide for the per-pipeline reproducibility floors.

## Plot

```bash
python3 plot_progress.py data/dalek-verus/progress.jsonl --png
```

Plots only `ok` samples; gaps are noted in the caption. The chart mode is
auto-detected from the records:

- **Colour** (Verus/Aeneas): one burn-up. `--in-progress` adds the yellow curve,
  `--unspecified` adds white.
- **Two-panel** (leanblueprint or lean): stacked Definitions and Theorems panels.
  The lean panels have no fixed ceiling, since `total` (the declaration count)
  grows over time.
- **Combined** (`--combined`, leanblueprint or lean): one panel pooling
  definitions and theorems, in the shared vocabulary below. Writes
  `burnup-combined.svg` and never overwrites the two-panel `burnup.svg`. The
  ceiling is a per-sample inventory that can fall as well as rise, so it is not
  a strictly monotonic burn-up. `--strict` exits non-zero if any sample violates
  the frontier nesting; the warning is stamped into the SVG either way.

`--png` also writes a PNG (via rsvg-convert, inkscape, or imagemagick);
`--png-scale` sets the raster scale (default 2.0).

**Scope caveat (leanblueprint combined).** It measures blueprint completion, not
repo-wide sorry debt. `in-progress` counts only formalized blueprint nodes whose
bindings hold a sorry; a sorry in a declaration the blueprint does not track is
invisible, so `in-progress = 0` means every formalized node is sorry-free, not
that the repo has none. Surfacing untracked sorry debt is
[#34](https://github.com/Beneficial-AI-Foundation/veritooling/issues/34). The
lean combined chart has no such blind spot: it counts every declaration, so its
`in-progress` is the project's full sorry count.

## Dependency graph & cross-project dashboard

Where the burn-up plots the scalar counts over time, `plot_depgraph.py` renders
the blueprint dependency graph for a single extract and `blueprint_dashboard.py`
compares several projects on one page. Both read the same
`probe-leanblueprint/extract` envelope and recompute everything from its per-node
data. The [graph guide](guides/graph-and-dashboard.md) is the walkthrough,
including how to produce an extract (the inputs are not committed, only the
rendered outputs).

Node grouping is by `blueprint-label`, one node per label, identical to
`blueprint_progress.py`'s counter. Solid edges are statement `\uses`; dashed
edges are proof `\uses`/`\proves`. The colouring adds two things the native
leanblueprint and Verso graphs cannot show:

- **machine-verified** (solid green): probe-lean's own `verification-status`
  rollup lands on `verified`, rather than a hand-toggled `\leanok`.
- **mismatch** (red outline): a node the blueprint claims proved but the machine
  refutes. Near-zero on code-derived Verso blueprints; the signal appears on
  Massot (`\leanok`-driven) blueprints.

The dashboard table is keyed on fractions, not raw counts, since node
granularity differs across projects. It shows **claimed** (the blueprint's
`fully-proved` claim) beside the stricter **machine-verified** rollup. Trust
detection is node-local: cross-node axiom reliance is not caught.

## Dependency-graph insights

`blueprint_insights.py` answers the graph-wide question the verso-blueprint
"Blueprint Summary" pages ask: closed versus blocked-by-a-dependency, a most-used
ranking, and an entry index, recomputed from `bp_graph` rather than copied from
any site. See the [graph guide](guides/graph-and-dashboard.md) for how to read
its output.

The closed/incomplete/sorry/no-proof split is computed twice. **claimed** reads
straight off `blueprint-proof-status` (per probe-leanblueprint's schema, `proved`
already means sorry-free and `fully-proved` means the node and its dependencies
are done, so no walk is needed). **machine** is an independent cross-check: a
walk over the same `\uses` edges gated on probe-lean's per-node status. On
carleson the machine column is stricter (140 closed rather than 154): some
theorems the blueprint calls closed rest on an axiom or an unclosed dependency.

Also reported: **actionable** entries (statement `ready` with every dependency
formalized, our reading of "the next step is unblocked"), **most used in
statements** and **most used in proofs** (two rankings, each by that column's own
direct-use count), and a full **entry index**. A dependency cycle is flagged
rather than silently mis-closed.

**What this cannot show.** The Lemma/Theorem/Proposition split some sites display
is not in the JSON graph model on any project checked; `kind` is only ever
`definition` or `theorem`. **Missing informal coverage** is recoverable only from
a raw `blueprint-manifest.json` at the same commit; pass it via `--manifest`
(`verso_manifest.py` merges several by label). Without it that section is omitted,
not reported as zero.

## How to read the charts

All charts share one vocabulary from the VeriLib "Atom statuses and colours" (FC)
model: **tracked** (the ceiling), **verified+trusted**, **verified**,
**in-progress**, **unspecified**, **failed**. What differs is the unit being
counted, stated on each chart's y-axis and subtitle. Read a chart as nested
frontiers, each larger band containing the smaller ones, plus zero-based status
counts drawn only when they occur.

**Colour** (Verus/Aeneas, unit: a Rust `exec` atom).
- **tracked**: atoms in scope (`exec_total` minus grey/disabled).
- **verified+trusted**: proved (green) plus axiom/trusted (purple). The
  completion frontier.
- **verified**: proved with no trust reliance (green).
- **in-progress** (yellow), **unspecified** (white), **failed** (red), and the
  Aeneas-only **translated** draw when present.
- The gap between `tracked` and `verified+trusted` is white plus yellow plus red.

**Blueprint two-panel** (leanblueprint, unit: a blueprint node; Definitions and
Theorems panels).
- **total**: every node of that kind. **formalized**: the Lean statement exists.
  **proved** (theorems only): sorry-free and probe-lean-confirmed.

**Lean two-panel** (lean, unit: a Lean declaration; no fixed ceiling).
- **total**: every declaration of that kind. **without sorry**:
  `verified + transitively-verified + trusted`. **trust boundary**:
  `transitively-verified + trusted`. **failed**: an elaboration error, drawn when
  present. The gap between `without sorry` and `trust boundary` is locally clean
  but transitively contaminated.

**Combined** (`--combined`, unit: a blueprint node or a Lean declaration, pooled).
Same FC bands as the colour burn-up. For leanblueprint the statement axis comes
from the blueprint and the proof status from probe-lean's per-atom
`verification-status`, rolled up per node by worst status; for lean both axes come
from probe-lean, so it sees every declaration. Curves draw only when present, so
a clean history stays uncluttered.

## Scheduling weekly updates (cron)

`--resume` makes the tool incremental and safe to run unattended: it fetches new
commits into the reused `--work-clone`, samples only commits not already recorded,
and leaves the file untouched on a week with no new commit. `--fail-on-error`
exits non-zero if any sample processed this run is not `ok`, so a wrapper's
`set -e` surfaces a broken week.

`cron/` has a ready-to-edit setup:

- `cron/update-progress.sh`: copy per project, edit the CONFIG block, `chmod +x`.
  It runs the sample, regenerates the chart, and commits the data if it changed.
  Run it once by hand first.
- `cron/example.crontab`: a Wednesday 07:00 schedule, so the newest sample is
  fresh for a Thursday review.

The wrapper handles the cron gotchas (a minimal `PATH`/`HOME`, overlap via
`flock`, publishing the result). The tool only writes files; the wrapper does the
`git add`/`commit`/`push`.

## Output

One JSON object per sampled commit, upserted by commit so `--retry-failed`
replaces a row rather than duplicating it; the CSV mirrors it. Shared columns:

`repo, pipeline, sample_date, commit, commit_date, tool, tool_version, status,
reason, commit_validated, duration_sec`.

Each pipeline then fills one metric group and leaves the others blank:

- **Colour** (Verus/Aeneas): `grey, white, red, yellow, light_green, dark_green,
  purple, exec_total, dot_red, dot_yellow, dot_green, art_total, tracked,
  verified, verified_trusted, translated`.
- **leanblueprint**: `bp_nodes_total, bp_nodes_bound, bp_nodes_planned,
  bp_nodes_decl_missing, bp_def_total, bp_def_formalized, bp_thm_total,
  bp_thm_formalized, bp_thm_proved, bp_thm_proved_confirmed`, plus, for
  `--combined`, a per-kind probe-lean partition over the formalized nodes:
  `bp_def_verified, bp_def_trusted, bp_def_in_progress, bp_def_failed,
  bp_def_unrealized` and the `bp_thm_*` counterparts.
- **lean**: `lean_def_total, lean_def_sorry, lean_def_verified,
  lean_def_trans_verified, lean_def_trusted, lean_def_failed` and the six
  `lean_thm_*` counterparts. `sorry` means the body has a sorry (`unverified`);
  `verified` is locally clean but transitively contaminated; `trans_verified` is
  clean to the trust base; `trusted` is an axiom or external decl; `failed` is an
  elaboration error. An `axiom` is bucketed with theorems.

`status` is one of `ok`, `setup_failed`, `checkout_failed`, `extract_failed`,
`verify_error`, `timeout`, `commit_mismatch`. Only `ok` samples are charted.
`verify_error` marks a commit that produced no per-function statuses (a render
yielding 0 blueprint nodes, or an extract with 0 declarations), a visible gap
rather than a real "0 verified" point. The two-axis and combined metrics are
detailed in `leanblueprint-metrics.md`.

## How it works

Clone once into `--work-clone`, never your own checkout. Bucket commits by period,
keep the latest in each, and always include HEAD. Oldest to newest: `git checkout
-f`, run the extract, then read the freshly written JSON and confirm its
`source.commit` matches the sample before recording. Verus installs the matching
release per commit; Aeneas, lean, and leanblueprint clean and refetch the Lean
build when `lean-toolchain` changes. leanblueprint also drops the previous
sample's Verso render each commit, since the tool reuses an existing render and
the commit-match guard is git-derived. With `--dep-cache-dir`, lean and
leanblueprint restore the compiled dependency build instead of recompiling.
Failures are recorded with a reason, not dropped.

## Tests

```bash
pip install ruff pytest
ruff format --check tools/ && ruff check tools/
pytest tools/verification-progress-history/tests -q
```

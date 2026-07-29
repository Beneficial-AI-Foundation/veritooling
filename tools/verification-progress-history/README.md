# verification-progress-history

Reconstruct a verification project's progress over its git history as a burn-up
time series. The tool samples one commit per period, re-runs the real verifier at
each, and records per-commit metrics to JSONL + CSV. `plot_progress.py` renders
these as a burn-up SVG. The metric set depends on the pipeline: the colour set
(`tracked`, `verified`, `verified+trusted`, `translated`) for Verus/Aeneas, and a
two-axis blueprint set (`formalized`, `proved`) for `leanblueprint`.

Standalone Python 3.10+ CLI, stdlib only at runtime. It is not a GitHub Action:
a multi-hour history walk with per-commit toolchain installs is a poor fit for CI.

Colour metric definitions live in the VeriLib docs,
[Atom statuses and colours](https://beneficial-ai-foundation.github.io/VeriLib-Docs/components/processor/atom-statuses-and-colours/);
reproduce them from any extract JSON with `colors.py <extract.json> --table`. The
blueprint two-axis definitions live in probe-leanblueprint's `docs/SCHEMA.md`;
reproduce them with `blueprint_progress.py <extract.json> --table`.

## Files

| File | Purpose |
|------|---------|
| `progress_history.py` | Sample history, checkout, run extract, write JSONL/CSV. |
| `colors.py` | Compute the colour metric record (Verus/Aeneas) from one extract JSON. |
| `blueprint_progress.py` | Compute the two-axis blueprint metric record (leanblueprint) from one extract JSON. |
| `plot_progress.py` | Render the burn-up chart (SVG, optional PNG). |
| `data/<name>/` | Committed outputs: `progress.{jsonl,csv}`, `burnup*.{svg,png}`. |

## Requirements

- Python 3.10+ and `git`.
- The probe for your pipeline on `PATH`, pinned to one version for the whole run:
  - Verus: [`probe-verus`](https://github.com/Beneficial-AI-Foundation/probe-verus) (installs verus-analyzer, scip, and the matching Verus).
  - Aeneas: [`probe-aeneas`](https://github.com/Beneficial-AI-Foundation/probe-aeneas) plus `elan` (runs Charon and `lake build`).
  - Lean blueprint: [`probe-leanblueprint`](https://github.com/Beneficial-AI-Foundation/probe-leanblueprint) plus `probe-lean` and `elan` (runs `probe-lean extract` and renders the Verso blueprint with `lake exe vbp build`).

## Run

One repo at a time; each sample re-verifies, so runs are long. Start with
`--dry-run` to list the sampled commits, then drop it. Re-invoke with `--resume`
to continue and `--retry-failed` to redo non-`ok` samples. Output defaults to
`data/<name>/progress.jsonl` (+ `.csv`).

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

`--since 2026-03-11` is the earliest reproducible commit: probe-lean needs Lean
>= v4.28.0-rc1 (reached 2026-02-23) and `probe-aeneas extract` needs
`aeneas-config.yml` (added 2026-03-11).

### secure-messaging (Lean blueprint)

```bash
python3 progress_history.py /path/to/secure-messaging \
  --pipeline leanblueprint --branch origin/main --since 2026-06-03 \
  --cadence monthly --work-clone /tmp/vph-sm --sample-timeout 14400 --resume \
  --verso-render-cmd 'BLUEPRINT_PROGRESS_HISTORY_SEED=0 scripts/render-docs-site.sh' \
  --dep-cache-dir /tmp/vph-dep-cache
```

`--since 2026-06-03` is where the `versoBlueprint` dependency was added, but the
earliest commit that actually *renders a graph manifest* is **2026-06-24**:
06-03 has no render script yet, and 06-10/06-17 render only a preview manifest
(no `blueprint-manifest.json`), so those three record `extract_failed` (probe-lean
runs, but there's no blueprint graph to enrich). The Lean toolchain has been >=
v4.28 throughout. `--branch origin/main` because the sampled repo's default
checkout may be a feature branch. This
pipeline records a two-axis blueprint metric set (see Output), not the colour
set; auto-detected from a `versoBlueprint` lakefile or a `blueprint/src/web.tex`
tree.

secure-messaging needs `--verso-render-cmd` because it renders per-chapter via
its own `scripts/render-docs-site.sh` rather than the default `lake exe vbp
build` (which fails with "could not find a blueprint-gen executable"). `SEED=0`
skips the script's `gh`-based history seeding. Any command that leaves
`blueprint-manifest.json` file(s) anywhere under `<blueprint-root>/_out/site`
works — probe-leanblueprint merges them.

**probe-lean is Lean-version-specific.** Each sample runs the
`probe-lean-v<toolchain>` matching that commit's `lean-toolchain` (selected from
`--probe-lean-dir`, default: the directory of `probe-lean` on `PATH`), so the
per-version binaries must be installed. A missing version is a clean
`setup_failed` for that sample. This also means a run can span a toolchain change
(here v4.29 -> v4.30) — but each change forces a full dependency rebuild (for
secure-messaging, VCVio has no prebuilt cache and takes a while), so a wide
window is slow; sample coarsely first.

`--dep-cache-dir` makes that rebuild a one-time cost. It snapshots the compiled
dependency builds keyed by `(Lean toolchain, lake manifest)` after the first
successful sample and restores them (seconds) on any later sample or run with the
same key, instead of recompiling. Since a project pins one dependency set per
toolchain, this collapses the per-toolchain VCVio compile + mathlib `cache get`
to a copy. It trades disk (~8 GB per key for secure-messaging, mostly mathlib) for
time and is safe to delete anytime. Point it at a persistent, roomy location to
make re-runs, `--retry-failed`, and finer cadences essentially free on the
dependency-build front.

The cache is consulted on a toolchain change or a fresh clone (when the dep
builds are wiped/absent). A same-toolchain sample keeps its dep builds and, if
only a dependency rev bumps within that toolchain, relies on lake's incremental
rebuild rather than a cache restore. Disabled for a sample with no
`lake-manifest.json` (the key would otherwise collapse to the toolchain alone).

### A single commit

To (re)sample one commit and update its row, pass `--commit` (repeatable) instead
of a date range. It runs those commits and upserts them by SHA, leaving the rest
of the series untouched. Useful for filling in a new HEAD or redoing a commit
that failed.

```bash
python3 progress_history.py /path/to/dalek-verus \
  --pipeline verus --project-subdir curve25519-dalek --package curve25519-dalek \
  --commit HEAD --work-clone /tmp/vph-dalek-verus
```

Other options: `--cadence {weekly,biweekly,monthly}` (or `--cadence-weeks N`),
`--anchor-day`, `--branch`, `--until`, `--output`/`--csv`, `--smt-seed`,
`--skip-verify`. Run `--help` for the full list.

## Plot

```bash
python3 plot_progress.py data/dalek-verus/progress.jsonl --png
```

Plots only `ok` samples (gaps are noted in the caption) and adds the `translated`
line for Aeneas data. `--in-progress` adds the `yellow` curve (incomplete proof:
sorry or assume); `--unspecified` adds `white` (tracked, no spec yet). Those are
distinct states, so do not read `tracked - verified` as the sorry count. `--png`
also writes a PNG via rsvg-convert, inkscape, or imagemagick, and `--png-scale`
sets the raster scale (default 2.0).

For a **leanblueprint** history the mode is auto-detected from the records and
two stacked panels are drawn instead, mirroring the published blueprint site:
**Definitions** (`total` + `formalized`) and **Theorems** (`total` +
`formalized` + `proved`). Terms are axis-explicit (see Output): *formalized* =
the statement is written in Lean; *proved* = the proof is sorry-free and
probe-lean-confirmed. `--in-progress`/`--unspecified` are colour-pipeline options
and are ignored here.

## Scheduling weekly updates (cron)

`--resume` makes the tool incremental and safe to run unattended: it fetches new
commits into the reused `--work-clone`, samples only commits not already
recorded (upserting by SHA), and leaves the file untouched on a week with no new
commit. `--fail-on-error` exits non-zero if any sample processed this run is not
`ok` (skipped/already-recorded samples don't count), so a wrapper's `set -e`
surfaces a broken week to cron mail or your log monitor.

`cron/` has a ready-to-edit setup:

- `cron/update-progress.sh` — copy per project, edit the CONFIG block,
  `chmod +x`. It runs the sample (`--resume --fail-on-error`), regenerates the
  chart, and commits the data if it changed. Run it once by hand first.
- `cron/example.crontab` — a Wednesday 07:00 schedule, so the newest sample is
  fresh for a Thursday review (the default `--anchor-day` is `wednesday`).

The wrapper handles the cron gotchas: a minimal `PATH`/`HOME` (the probe and
toolchain must resolve for the cron user), overlap (`flock`), and publishing the
result — the tool only writes files, so the wrapper does the `git add/commit/push`
(to a bot data branch by default; adapt that step to your workflow).

## Output

One JSON object per sampled commit, upserted by commit so `--retry-failed`
replaces a row rather than duplicating it; the CSV mirrors it. Columns:

`repo, pipeline, sample_date, commit, commit_date, tool, tool_version, status,
reason, commit_validated, duration_sec, grey, white, red, yellow, light_green,
dark_green, purple, exec_total, dot_red, dot_yellow, dot_green, art_total,
tracked, verified, verified_trusted, translated`

The `leanblueprint` pipeline fills a separate two-axis set instead (the colour
columns above stay blank, as `translated` does for non-Aeneas):

`bp_nodes_total, bp_nodes_bound, bp_nodes_planned, bp_nodes_decl_missing,
bp_def_total, bp_def_formalized, bp_thm_total, bp_thm_formalized, bp_thm_proved,
bp_thm_proved_confirmed`

A blueprint node has two axes (see probe-leanblueprint's `docs/SCHEMA.md`):
*statement* (`formalized` = the Lean statement/signature exists) and *proof*
(`fully-proved` = sorry-free). `bp_*_formalized` counts statement-`formalized`
nodes; `bp_thm_proved` counts the blueprint's `fully-proved` claim, and
`bp_thm_proved_confirmed` the **probe-lean-confirmed** subset (bound, whole
binding present, not contradicted by probe-lean) — the honest headline, matching
probe-leanblueprint's `theorems-fully-proved-probe-lean-confirmed`. `bp_nodes_*`
split every node into bound (has a decl), planned-only (a pure stub), and
decl-missing (an over-claim).

`status` is one of `ok`, `setup_failed`, `checkout_failed`, `extract_failed`,
`verify_error`, `timeout`, `commit_mismatch`. Only `ok` samples are charted;
`verify_error` marks a commit that produced no per-function statuses (for
leanblueprint, a render yielding 0 blueprint nodes) — a visible gap, not a real
"0 verified" point.

## How it works

Clone once into `--work-clone`, never your own checkout. Bucket commits by
period, keep the latest in each, always include HEAD. Oldest to newest: `git
checkout -f`, run extract, then read the freshly written JSON and confirm its
`source.commit` matches the sample before recording. Verus installs the matching
release per commit; Aeneas and leanblueprint clean and refetch the Lean build
when `lean-toolchain` changes. leanblueprint also drops the previous sample's
Verso render (`_out/site`) each commit, since the tool reuses an existing render
and `source.commit` is git-derived (so the commit-match guard would not catch a
stale one). With `--dep-cache-dir`, leanblueprint restores the compiled
dependency builds (keyed by toolchain + manifest) instead of recompiling them on
a toolchain change or fresh clone. Failures are recorded with a reason, not
dropped.

## Tests

```bash
pip install ruff pytest
ruff format --check tools/ && ruff check tools/
pytest tools/verification-progress-history/tests -q
```

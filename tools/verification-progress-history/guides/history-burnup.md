# Guide: verification burn-up over history

**The question this answers:** how has a project's verification progressed over
its git history? You get a burn-up time series (one sample per period) as JSONL
plus CSV, and a burn-up chart.

**Scripts, in run order:**

```
progress_history.py            sample commits, checkout, run the real verifier
  colors.py                    Verus/Aeneas colour metric per extract
  blueprint_progress.py        leanblueprint two-axis metric per extract
  lean_progress.py             plain-lean kind-split sorry metric per extract
plot_progress.py               render the burn-up chart from the JSONL
```

`progress_history.py` picks the metric module from `--pipeline` (auto-detected
for Lean). You never call the metric modules through the sampler; you can call
them standalone on one extract to print the metric table (see "Inspect one
commit's numbers").

## Reproduce a chart from committed data (cheap, no verifier)

The expensive part is sampling: it re-runs the verifier at every commit.
Plotting is free and needs only the committed `progress.jsonl`. Run from the
tool's directory:

```bash
python3 plot_progress.py data/dalek-verus/progress.jsonl -o /tmp/burnup.svg
```

This regenerates the committed `data/dalek-verus/burnup.svg` from its source
JSONL. It draws the three categories and nothing else; each further curve is one
flag (`--trusted`, `--unspecified`, `--failed`, `--translated`, `--unrealized`),
and `--png` writes a raster copy.

The other pipelines' committed series work the same way:

| Data dir | Pipeline | Chart |
|----------|----------|-------|
| `data/dalek-verus/` | Verus | unit: `exec` atom |
| `data/SparsePostQuantumRatchet-verify/` | Aeneas | unit: `exec` atom (`--translated` available) |
| `data/secure-messaging/` | leanblueprint | unit: blueprint node, defs and thms pooled |
| `data/kvac-model-from-probe-lean/` | lean | unit: declaration, defs and thms pooled; ceiling labelled `total` |

The unit is auto-detected from the records; you do not pass `--pipeline` to
`plot_progress.py`. For the two Lean series, `--split` renders the older
diagnostic two-panel layout into `burnup-split.svg` instead.

## Inspect one commit's numbers

Each metric module prints its own table for a single extract JSON, which is how
the committed columns are defined:

```bash
python3 colors.py <extract.json> --table            # Verus/Aeneas colour set
python3 blueprint_progress.py <extract.json> --table # leanblueprint two-axis set
python3 lean_progress.py <extract.json> --table      # plain-lean kind-split set
```

## Regenerate the series from scratch (expensive)

This walks history and re-verifies each sampled commit: hours, with per-commit
toolchain installs. Do it only to extend or rebuild a series, not to look at one.
The exact command behind each committed series is in
[`../data/README.md`](../data/README.md); the dalek-verus series, for example:

```bash
python3 progress_history.py /path/to/dalek-verus \
  --pipeline verus --project-subdir curve25519-dalek --package curve25519-dalek \
  --since 2025-07-14 --work-clone /tmp/vph-dalek-verus \
  --sample-timeout 7200 --resume
```

Start with `--dry-run` to list the commits it would sample. `--resume` continues
an interrupted run, `--retry-failed` redoes any non-`ok` sample, and `--commit
HEAD` refreshes just the latest point. Per-pipeline reproducibility floors (Lean
version, config files) are in the [tool README](../README.md#run) and
`data/README.md`.

## What to look at in the chart

Three curves:

- **tracked** (ceiling): everything in scope.
- **completed**: `verified + transitively-verified + trusted`. The project is done
  on the chart when this meets the ceiling.
- **in-progress**: a spec exists but the proof is not closed (a `sorry` or
  `assume`).

`completed` and `in-progress` are disjoint but do not sum to `tracked`. What is
left over is `unspecified` (in scope, no spec yet) plus `failed`, so the gap must
not be read as the sorry count. `--unspecified` and `--failed` split it open, and
`--trusted` adds the axiom-backed part of `completed`. A withheld `--failed` count
is still printed on stderr, so a failing sample cannot pass unnoticed.

Only `ok` samples are plotted; other statuses (`setup_failed`, `extract_failed`,
`timeout`, …) show as gaps noted in the caption. The full vocabulary and the
per-pipeline chart variants are in the
[tool README](../README.md#how-to-read-the-charts).

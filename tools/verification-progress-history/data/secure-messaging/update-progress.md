# Update secure-messaging progress + chart

Run everything from the tool directory:

```bash
cd tools/verification-progress-history
```

Data lives in `data/secure-messaging/`. Last recorded sample: **2026-08-12**
(`progress.jsonl`, 8 rows). Sampling re-runs the real verifier per commit, so it
is slow (~13–18 min/commit here); plotting is free.

The committed series is **weekly** (Wednesday-anchored: 2026-06-24 … 2026-08-12),
so extend it with `--cadence weekly`.

## Prerequisites (on PATH, pinned for the whole run)

`elan`, `probe-leanblueprint`, and the `probe-lean-v<toolchain>` matching each
sampled commit's `lean-toolchain` (probe-lean reads version-specific `.olean`s).
If new commits bumped the Lean toolchain, that version must be present or the
sample records `setup_failed`; add `--install-probe-lean` to auto-fetch it.

## 1. Add new data points

`--resume` upserts by commit SHA and skips anything already recorded, so a
week with no new commit adds nothing:

```bash
python3 progress_history.py <repo> \
  --pipeline leanblueprint --cadence weekly \
  --verso-render-cmd scripts/render-docs-site.sh \
  --since 2026-08-12 --resume \
  --work-clone /tmp/vph-secure-messaging \
  --dep-cache-dir /tmp/vph-depcache \
  --sample-timeout 3600
```

- `--dry-run` first to list the commits it would sample.
- `--dep-cache-dir` snapshots the compiled dep build per (toolchain, manifest)
  and restores it in seconds on later samples — keep it persistent to make
  reruns cheap. A run crossing a toolchain change forces a full rebuild.
- To refresh just the latest point instead of walking the cadence grid, drop
  `--since/--resume` and pass `--commit HEAD` (repeatable; always re-runs).
- `--retry-failed` (with `--resume`) redoes any past non-`ok` sample.

`progress.jsonl` and `progress.csv` are rewritten in place.

## 2. Regenerate the chart

Free, no verifier. Reproduces the committed SVG/PNG from the JSONL:

```bash
python3 plot_progress.py data/secure-messaging/progress.jsonl --png
```

Writes `burnup.svg`/`.png` alongside the JSONL: one panel, blueprint nodes pooled
across definitions and theorems, drawing `tracked` / `in-progress` / `completed`
with the proof status from probe-lean. This is the only committed chart.

Optional views, none of them committed: `--unspecified` adds the nodes with no
formalized statement yet, `--unrealized` the ones claiming a statement with no
bound declaration, `--trusted` the axiom-backed part of `completed`, and `--split`
writes the diagnostic two-panel `burnup-split.svg` in the blueprint's own
`total`/`formalized`/`proved` vocabulary.

Only `ok` samples are plotted; other statuses show as captioned gaps. See
[`../../guides/history-burnup.md`](../../guides/history-burnup.md) and
[`../../leanblueprint-metrics.md`](../../leanblueprint-metrics.md) for the metric
definitions.

# data

Committed outputs from [`verification-progress-history`](../), one folder per
project (`<name>/`):

- `progress.jsonl`: source of truth, one record per sampled commit (upserted by
  commit on re-runs, not appended).
- `progress.csv`: flat view regenerated from the JSONL, for plotting.
- `burnup.svg` / `.png` (and `burnup-inprogress.*`): rendered charts.

Each backfill re-runs verification per sample and is expensive, so the outputs
are committed here rather than regenerated on demand. See [`../README.md`](../README.md)
for the record schema and run commands.

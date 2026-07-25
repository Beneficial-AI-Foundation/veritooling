# data

Committed time-series outputs from the
[`verification-progress-history`](../tools/verification-progress-history/) tool.

Each run produces a pair of files per project:

- `progress-<name>.jsonl` — append-only source of truth, one record per sample.
- `progress-<name>.csv` — flattened view regenerated from the JSONL, for plotting.

These are generated deliberately (each backfill re-runs verification per weekly
sample and is expensive), then committed here so the burn-up history is shared
in one place next to the tool. See the tool README for the record schema and the
per-project run commands.

# data

Committed time-series outputs from the
[`verification-progress-history`](../tools/verification-progress-history/) tool.

One folder per project (`<name>/`), each containing:

- `progress.jsonl` — source of truth, one record per sampled commit (upserted in
  place on re-runs, so a revised sample replaces its prior row, not appends).
- `progress.csv` — flattened view regenerated from the JSONL, for plotting.
- `burnup.svg` / `burnup.png` — the burn-up chart (+ `burnup-inprogress.*` when
  the status curves are rendered).

These are generated deliberately (each backfill re-runs verification per weekly
sample and is expensive), then committed here so the burn-up history is shared
in one place next to the tool. See the tool README for the record schema and the
per-project run commands.

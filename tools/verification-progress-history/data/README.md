# data

Committed outputs from [`verification-progress-history`](../), one folder per
project (`<name>/`):

- `progress.jsonl`: source of truth, one record per sampled commit, upserted
  by commit on rerun, not appended.
- `progress.csv`: flat view regenerated from the JSONL, for plotting.
- `burnup.svg` / `.png` (and `burnup-inprogress.*`): rendered charts.
- `depgraph.svg` / `.dot` (leanblueprint projects only): the dependency graph
  for one commit's extract, from `plot_depgraph.py`. A snapshot, not a
  history; see each file's own header for its source commit.
- `insights.txt` / `.html` (leanblueprint projects only): the
  closure/ranking/entry-index report from `blueprint_insights.py --table` /
  `--html`, for the same commit as `depgraph.*`. Includes a `--manifest`
  cross-check (missing informal coverage) only where noted in the file; most
  projects don't have a current raw manifest on disk to cross-reference.

Each backfill re-runs verification per sample and is expensive, so the
outputs are committed here rather than regenerated on demand. See
[`../README.md`](../README.md) for the record schema and run commands.

`kvac-model/` and `all-blueprints/` hold dependency-graph-only snapshots, no
`progress.jsonl` history yet. `kvac-model/depgraph.*` and `insights.*` are
KVAC's blueprint graph and insights report at commit `ab91ef60`.
`all-blueprints/` is the cross-project dashboard (`blueprint_dashboard.py`);
its `index.html` currently only covers KVAC, since that's the only project
with a fresh local extract right now. The other five projects' `.dot`/`.svg`/
`.insights.txt` files (FLT, carleson, Sphere-Packing-Lean, Noperthedron,
secure-messaging) are still on disk from an earlier run but aren't linked from
`index.html` until they're re-extracted.

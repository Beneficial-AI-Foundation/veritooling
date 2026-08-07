# data

Committed outputs from [`verification-progress-history`](../), one folder per
project (`<name>/`):

- `progress.jsonl`: source of truth, one record per sampled commit, upserted by
  commit on rerun (not appended).
- `progress.csv`: flat view regenerated from the JSONL, for plotting.
- `burnup.svg`/`.png`: the rendered chart, one per project, in the three
  categories `tracked` / `in-progress` / `completed`. Regenerate with
  `plot_progress.py <name>/progress.jsonl --png`; the overlay flags
  (`--trusted`, `--unspecified`, …) and `--split` write to other paths and are not
  committed.
- `depgraph.svg`/`.dot` (leanblueprint only): the dependency graph for one
  commit's extract, from `plot_depgraph.py`. A snapshot, not a history; see each
  file's own header for its source commit.
- `insights.txt`/`.html` (leanblueprint only): the closure/ranking/entry-index
  report from `blueprint_insights.py`, for the same commit as `depgraph.*`.

Each backfill re-runs verification per sample and is expensive, so the outputs
are committed here rather than regenerated on demand. See
[`../README.md`](../README.md) for the record schema, and the
[guides](../guides/) for the walkthroughs.

## Provenance

What each directory holds and how to reproduce it. The plotting and insights
steps are cheap; the sampling behind every `progress.jsonl` is a multi-hour
history walk (see the run command in the [tool README](../README.md#run)). The
`--work-clone`/`--since` shown are the committed run's; adjust paths to yours.

| Directory | Pipeline | Source | Reproducible from committed data? |
|-----------|----------|--------|-----------------------------------|
| `dalek-verus/` | Verus | `progress_history.py --pipeline verus --since 2025-07-14` | Chart: `plot_progress.py dalek-verus/progress.jsonl`. Series: rerun sampler. |
| `SparsePostQuantumRatchet-verify/` | Aeneas | `progress_history.py --pipeline aeneas --since 2026-03-13` | Chart: yes, from its `progress.jsonl`. Series: rerun sampler. |
| `curve25519-dalek-lean-verify/` | Aeneas | `progress_history.py --pipeline aeneas --since 2026-03-11 --cadence monthly` | Chart: yes. Series: rerun sampler (floor: Lean >= v4.28.0-rc1 and `aeneas-config.yml`). |
| `secure-messaging/` | leanblueprint | `progress_history.py --pipeline leanblueprint --since 2026-06-03 --cadence weekly` (plus `--verso-render-cmd`); `depgraph.*`/`insights.txt` from one commit's extract | Chart: yes; step-by-step in [`secure-messaging/update-progress.md`](secure-messaging/update-progress.md). Graph/insights: need an extract (not committed). |
| `kvac-model-from-probe-lean/` | lean | `progress_history.py --pipeline lean --cadence monthly` over KVAC-model | Chart: yes, including `--split`. Series: rerun sampler. |
| `kvac-model-blueprint/` | leanblueprint | Projected history through 2026-07-15 (`tool: projection`; see [`../leanblueprint-metrics.md`](../leanblueprint-metrics.md)) spliced with real per-commit samples from 2026-08-05 on: `progress_history.py --pipeline leanblueprint --cadence weekly --verso-render-cmd <abs>/scripts/build-blueprint.sh` over KVAC-model. The render path must be absolute: KVAC's Verso project lives under `docs/`, so probe-leanblueprint runs the cmd with cwd `docs/` and a repo-relative `scripts/...` fails (127). Real samples need Lean ≥ v4.30.0 (the versoBlueprint port); earlier commits have no blueprint to read, which is what the projection covers. | Chart: yes, including `--split`. Real points: rerun sampler. |
| `kvac-model/` | leanblueprint | `plot_depgraph.py` / `blueprint_insights.py` on KVAC's extract at commit `ab91ef60` | Graph/insights only. Need the extract (not committed) to regenerate. |
| `all-blueprints/` | leanblueprint | `blueprint_dashboard.py` over several extracts | Need the extracts (not committed) to regenerate. |
| `verso-comparison/` | leanblueprint | our graph/insights vs verso-blueprint's published pages, four reference blueprints at their pinned commits; see [`../guides/verso-blueprint-comparison.md`](../guides/verso-blueprint-comparison.md) | Our side: need the extracts. verso side: screenshots of the live pages. |

`kvac-model/` and `all-blueprints/` are dependency-graph snapshots, no history
yet. `all-blueprints/index.html` currently covers only KVAC, the sole project
with a fresh local extract; the other five projects' `.dot`/`.svg`/`.insights.txt`
files (FLT, carleson, Sphere-Packing-Lean, Noperthedron, secure-messaging) are on
disk from an earlier run but are not linked from `index.html` until re-extracted.

For the graph/insights/dashboard directories, the input `extract.json` envelopes
are not committed (they need a built Lean project and are large). See
[`../guides/graph-and-dashboard.md`](../guides/graph-and-dashboard.md) for how to
generate one and re-render these outputs.

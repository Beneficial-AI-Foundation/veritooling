# verification-progress-history

Reconstruct a verification project's progress over its git history as a burn-up
time series. The tool samples one commit per period, re-runs the real verifier at
each, and records per-commit metrics (`tracked`, `verified`, `verified+trusted`,
`translated`) to JSONL + CSV. `plot_progress.py` renders these as a burn-up SVG.

Standalone Python 3.10+ CLI, stdlib only at runtime. It is not a GitHub Action:
a multi-hour history walk with per-commit toolchain installs is a poor fit for CI.

Metric definitions live in the VeriLib docs,
[Atom statuses and colours](https://docs.verilib.org/components/processor/atom-statuses-and-colours/).
Reproduce the numbers from any extract JSON with `colors.py <extract.json> --table`.

## Files

| File | Purpose |
|------|---------|
| `progress_history.py` | Sample history, checkout, run extract, write JSONL/CSV. |
| `colors.py` | Compute the metric record from one extract JSON. |
| `plot_progress.py` | Render the burn-up chart (SVG, optional PNG). |
| `data/<name>/` | Committed outputs: `progress.{jsonl,csv}`, `burnup*.{svg,png}`. |

## Requirements

- Python 3.10+ and `git`.
- The probe for your pipeline on `PATH`, pinned to one version for the whole run:
  - Verus: [`probe-verus`](https://github.com/Beneficial-AI-Foundation/probe-verus) (installs verus-analyzer, scip, and the matching Verus).
  - Aeneas: [`probe-aeneas`](https://github.com/Beneficial-AI-Foundation/probe-aeneas) plus `elan` (runs Charon and `lake build`).

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

## Output

One JSON object per sampled commit, upserted by commit so `--retry-failed`
replaces a row rather than duplicating it; the CSV mirrors it. Columns:

`repo, pipeline, sample_date, commit, commit_date, tool, tool_version, status,
reason, commit_validated, duration_sec, grey, white, red, yellow, light_green,
dark_green, purple, exec_total, dot_red, dot_yellow, dot_green, art_total,
tracked, verified, verified_trusted, translated`

`status` is one of `ok`, `setup_failed`, `checkout_failed`, `extract_failed`,
`verify_error`, `timeout`, `commit_mismatch`. Only `ok` samples are charted;
`verify_error` marks a commit that produced no per-function statuses (a visible
gap, not a real "0 verified" point).

## How it works

Clone once into `--work-clone`, never your own checkout. Bucket commits by
period, keep the latest in each, always include HEAD. Oldest to newest: `git
checkout -f`, run extract, then read the freshly written JSON and confirm its
`source.commit` matches the sample before recording. Verus installs the matching
release per commit; Aeneas cleans and refetches the Lean build when
`lean-toolchain` changes. Failures are recorded with a reason, not dropped.

## Tests

```bash
pip install ruff pytest
ruff format --check tools/ && ruff check tools/
pytest tools/verification-progress-history/tests -q
```

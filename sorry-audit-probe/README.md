# sorry-audit-probe

Generate a sorry manifest using [probe-lean](https://github.com/Beneficial-AI-Foundation/probe-lean)
for sorry detection via build warning parsing. Zero configuration required.

## What It Detects

- Declarations whose own body uses `sorry` (via Lean build warnings)
- Declarations marked as not verified in probe-lean's verification-status field

Current limitation: detection is shallow (own-body only, not transitive through
dependencies). Transitive propagation is planned as
[probe#11](https://github.com/Beneficial-AI-Foundation/probe/issues/11).

## Prerequisites

- `lake build` must have completed successfully before this action runs
- No project-specific configuration needed

## Usage

```yaml
- uses: leanprover/lean-action@v1
  with:
    build: true

- uses: Beneficial-AI-Foundation/veritooling/sorry-audit-probe@v1
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `project-path` | no | `.` | Path to Lean project |
| `manifest-path` | no | `sorry-manifest.txt` | Output manifest path |
| `probe-lean-ref` | no | `main` | Git ref for probe-lean |

## Outputs

| Output | Description |
|--------|-------------|
| `manifest-path` | Path to the generated manifest |
| `sorry-count` | Total sorry-tainted declaration count |
| `probe-results` | Path to probe-lean JSON (for specs-delta probe mode) |

## How It Works

1. Runs `probe-lean extract` via the probe-lean GitHub Action
2. Converts the probe-lean JSON output to `# sorry-manifest v1` format
3. Maps `verification-status` values to `direct` / `transitive` kinds

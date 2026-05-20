# veritooling

Reusable CI toolkit for Lean 4 verification projects. Track sorry-tainted
declarations, detect spec changes, and surface verification deltas as PR
comments -- without copying scripts into every repo.

## Quick Start

Add two workflow files to your repository and you're done.

**`.github/workflows/lean-ci.yml`** -- builds and audits:

```yaml
name: Lean CI
on:
  push:
    branches: ['**']
  pull_request:
    branches: ['**']

jobs:
  build:
    uses: Beneficial-AI-Foundation/veritooling/.github/workflows/lean-build-audit.yml@v1
    with:
      sorry-backend: probe
```

**`.github/workflows/verification-comment.yml`** -- posts the PR comment:

```yaml
name: Verification Comment
on:
  workflow_run:
    workflows: ["Lean CI"]
    types: [completed]

jobs:
  comment:
    uses: Beneficial-AI-Foundation/veritooling/.github/workflows/verification-comment.yml@v1
```

That's it. Every PR gets a sticky **Verification Delta** comment showing new
and removed sorry-tainted declarations.

## Actions

Each action is a self-contained composite action. Use the reusable workflows
above for convenience, or compose individual actions into your own workflow.

| Action | Phase | Purpose |
|--------|-------|---------|
| [`sorry-audit-collectaxioms`](sorry-audit-collectaxioms/) | Generation | Axiom-closure sorry detection via Lean metaprogramming |
| [`sorry-audit-probe`](sorry-audit-probe/) | Generation | Sorry detection via [probe-lean](https://github.com/Beneficial-AI-Foundation/probe-lean) |
| [`specs-delta`](specs-delta/) | Generation | Detect spec theorem changes (`git-diff` or `probe` mode) |
| [`sorry-delta`](sorry-delta/) | Reporting | Compute sorry manifest diff, format markdown |
| [`verification-delta-report`](verification-delta-report/) | Reporting | Combine sorry-delta + specs-delta into one PR comment |

### Generation vs Reporting

**Generation actions** run in the build job (`pull_request` trigger) and produce
data files. They need no write permissions and can safely run untrusted PR code.

**Reporting actions** run in a separate `workflow_run`-triggered job with
`pull-requests: write`. They consume artifacts from the build job and produce
the PR comment. This split ensures fork PRs get comments without exposing write
tokens to untrusted code.

See [docs/SECURITY.md](docs/SECURITY.md) for the full threat model.

## Sorry Audit Backends

### `collectAxioms` -- deep analysis

Uses Lean's `collectAxioms` API to detect sorry-tainted declarations
transitively through the dependency graph. Also detects `Lean.trustCompiler`,
custom axioms, and traces the BFS path from sorry origins to spec theorems.

Requires specifying the root module name. Best for Aeneas extraction projects
and security-critical verification work.

```yaml
- uses: Beneficial-AI-Foundation/veritooling/sorry-audit-collectaxioms@v1
  with:
    root-module: Spqr
    specs-prefix: Spqr.Specs   # optional
```

### `probe-lean` -- zero configuration

Uses [probe-lean](https://github.com/Beneficial-AI-Foundation/probe-lean) to
detect sorry-tainted declarations via build warning parsing. Auto-detects the
root module from `lakefile.toml`. Works on any Lean 4 project.

```yaml
- uses: Beneficial-AI-Foundation/veritooling/sorry-audit-probe@v1
```

## Specs Delta

Detect which specification theorems a PR added, removed, or changed.

**`git-diff` mode** (lightweight, no external dependencies):

```yaml
- uses: Beneficial-AI-Foundation/veritooling/specs-delta@v1
  with:
    mode: git-diff
    specs-paths: MyProject/Specs
    base-ref: ${{ github.event.pull_request.base.sha }}
```

**`probe` mode** (declaration-level, requires probe-lean JSON):

```yaml
- uses: Beneficial-AI-Foundation/veritooling/specs-delta@v1
  with:
    mode: probe
    probe-base-json: probe-base.json
    probe-head-json: probe-head.json
```

## Manifest Format

The sorry manifest uses a simple versioned text format:

```
# sorry-manifest v1
Spqr.Code.Funs some.declaration.name direct
Spqr.Specs.Thm another.theorem transitive
```

See the [sorry-delta README](sorry-delta/) for format details.

## Documentation

- [docs/SECURITY.md](docs/SECURITY.md) -- Threat model and security hardening
- [docs/INTEGRATION.md](docs/INTEGRATION.md) -- Step-by-step setup guides

## License

Apache-2.0

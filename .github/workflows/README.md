# Workflows

These reusable workflows build a Lean 4 project and turn its `sorry`/axiom
state into a pull-request comment. Reference them from your own repository with
`uses: Beneficial-AI-Foundation/veritooling/.github/workflows/<file>@v1`.

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `lean-build-audit.yml` | your `pull_request` / `push` job | Build the project and generate audit artifacts (sorry manifest, optional specs delta). |
| `verification-comment.yml` | `workflow_run` after the build | Read those artifacts and post the verification-delta comment. |
| `self-test.yml` | this repo only | Internal CI for veritooling; not for consumers. |

The two run as separate jobs by design: the build runs untrusted PR code with
no write access, while the comment job — which needs `pull-requests: write` —
only ever sees the artifacts the build produced. This lets fork PRs get
comments without exposing a write token to untrusted code.

## How a report is generated

```
lake build  ──▶  audit (manifest + console report)  ──▶  delta vs base  ──▶  PR comment
            (lean-build-audit.yml)                     (verification-comment.yml)
```

1. **Build** — `leanprover/lean-action` compiles the project.
2. **Audit** — one of two backends scans the build and writes
   `sorry-manifest.txt`, a versioned list of every sorry-tainted declaration:
   - `collectaxioms` — a Lean metaprogram that walks the transitive axiom
     closure of each declaration (catches `sorry` reached indirectly, plus
     `Lean.trustCompiler` and custom axioms). Also prints the console report
     described below.
   - `probe` — parses build warnings via
     [probe-lean](https://github.com/Beneficial-AI-Foundation/probe-lean). Zero
     config; auto-detects the root module.
3. **Baseline** — the base branch's manifest is restored from cache as
   `sorry-manifest-base.txt`.
4. **Report** — `sorry-delta` diffs head against base; `specs-delta` optionally
   reports added/removed specification theorems; `verification-delta-report`
   combines them into one sticky **Verification Delta** comment listing the
   `sorry` declarations a PR adds or removes.

### The `collectAxioms` console report

When the `collectaxioms` backend runs it logs four sections:

1. **Axiom & sorry audit** — per declaration, the non-builtin axioms it depends
   on, and whether `sorry` or `Lean.trustCompiler` appear. Covers the *in-focus*
   modules (see `exclude-module` below).
2. **Where does `sorry` come from?** — every declaration whose own body uses
   `sorry`, then a BFS path showing how `sorry` reaches each in-focus theorem.
3. **Full project summary** — aggregate counts over *all* root modules.
4. **Sorry manifest** — the machine-readable `sorry-manifest.txt` that feeds the
   delta.

`exclude-module` narrows only Sections 1–2 (the detailed view). Sections 3–4
always cover every in-project module, so excluded code still appears in the
summary and the manifest.

## Setup

Two files in your repository.

**`.github/workflows/lean-ci.yml`** — build and audit:

```yaml
name: Lean CI
on:
  pull_request:
  push:
    branches: [main]

jobs:
  build:
    uses: Beneficial-AI-Foundation/veritooling/.github/workflows/lean-build-audit.yml@v1
    with:
      sorry-backend: probe        # zero-config; or `collectaxioms` (below)
```

**`.github/workflows/verification-comment.yml`** — post the comment:

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

### collectAxioms backend

For transitive axiom-closure analysis and `sorry` provenance, swap the build
job's `with:` block:

```yaml
    with:
      sorry-backend: collectaxioms
      root-module: MyProject               # optional: one or more roots. If omitted,
                                           # auto-detected from lakefile.toml defaultTargets
      exclude-module: Extracted            # optional: keep generated code out of
                                           # the detailed view (Sections 1–2)
```

### Reducing comment noise

On projects that carry `sorry`s in generated/extracted code, gate the comment
on hand-written modules so it only fires when a *new* hand-written `sorry`
appears:

```yaml
jobs:
  comment:
    uses: Beneficial-AI-Foundation/veritooling/.github/workflows/verification-comment.yml@v1
    with:
      include-prefix: MyProject            # ignore sorries outside these modules
```

## Inputs

`lean-build-audit.yml` and `verification-comment.yml` each expose their inputs
inline at the top of the file. The actions they call are documented per
directory: [`sorry-audit-collectaxioms`](../../actions/sorry-audit-collectaxioms),
[`sorry-audit-probe`](../../actions/sorry-audit-probe),
[`sorry-delta`](../../actions/sorry-delta), [`specs-delta`](../../actions/specs-delta),
[`verification-delta-report`](../../actions/verification-delta-report).

To compose the individual actions into a hand-written pipeline instead of using
these workflows, read those action READMEs — the wiring mirrors the steps above.

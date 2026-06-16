# Integration Guide

Step-by-step guides for adding veritooling to your Lean 4 project.

## Guide 1: Standard Lean Project (probe-lean backend, zero config)

Best for: any Lean 4 project that builds with `lake build`.

### Step 1: Add the build workflow

Create `.github/workflows/lean-ci.yml`:

```yaml
name: Lean CI
on:
  push:
    branches: ['**']
  pull_request:
    branches: ['**']
  workflow_dispatch:

jobs:
  build:
    uses: Beneficial-AI-Foundation/veritooling/.github/workflows/lean-build-audit.yml@v1
    with:
      sorry-backend: probe
```

### Step 2: Add the comment workflow

Create `.github/workflows/verification-comment.yml`:

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

That's it. PRs will now get a sticky "Verification Delta" comment.

## Guide 2: Aeneas Extraction Project (collectAxioms backend)

Best for: projects using Aeneas with a `Specs.*` module convention, where you
want deep axiom-closure analysis and sorry provenance tracing.

### Step 1: Add the build workflow

Create `.github/workflows/lean-ci.yml`:

```yaml
name: Lean CI
on:
  push:
    branches: ['**']
  pull_request:
    branches: ['**']
  workflow_dispatch:

jobs:
  build:
    uses: Beneficial-AI-Foundation/veritooling/.github/workflows/lean-build-audit.yml@v1
    with:
      sorry-backend: collectaxioms
      root-module: MyProject                   # your root module(s); e.g. "MyProject,Extracted"
      specs-prefix: MyProject.Specs            # your specs prefix
      specs-delta-mode: git-diff
      specs-paths: MyProject/Specs             # directory containing spec files
```

### Step 2: Add the comment workflow

Same as Guide 1.

## Guide 3: Adding Specs Delta to an Existing Setup

If you already have a build workflow and just want to add specs change
detection.

### Option A: git-diff mode (no probe-lean needed)

Add this step to your existing build job, after `lake build`:

```yaml
- uses: Beneficial-AI-Foundation/veritooling/specs-delta@v1
  with:
    mode: git-diff
    specs-paths: MyProject/Specs
    base-ref: ${{ github.event.pull_request.base.sha }}
```

Upload `specs-delta.json` and `.specs-delta-section.md` as artifacts alongside
your sorry manifests.

### Option B: probe mode (requires probe-lean JSON on base and head)

```yaml
- uses: Beneficial-AI-Foundation/veritooling/specs-delta@v1
  with:
    mode: probe
    probe-base-json: probe-base.json
    probe-head-json: probe-head.json
```

## Guide 4: Migrating from a Hand-Rolled Pipeline

If your project currently has `scripts/Audit.lean` and `scripts/sorry-diff.py`
(as in the SparsePostQuantumRatchet-verify repository).

### Step 1: Update the build workflow

Replace your audit steps with the veritooling action.

**Before:**

```yaml
- name: Axiom audit and sorry manifest
  run: lake env lean scripts/Audit.lean
```

**After:**

```yaml
- uses: Beneficial-AI-Foundation/veritooling/sorry-audit-collectaxioms@v1
  with:
    root-module: MyProject
    specs-prefix: MyProject.Specs
```

Keep your existing baseline caching and artifact upload steps.

### Step 2: Update the comment workflow

Replace your sorry-diff invocation:

**Before:**

```yaml
- name: Compute sorry delta
  run: python3 scripts/sorry-diff.py sorry-manifests/sorry-manifest-base.txt sorry-manifests/sorry-manifest.txt

- name: Post PR comment
  uses: marocchino/sticky-pull-request-comment@v2
  with:
    header: sorry-delta
    number: ${{ steps.pr.outputs.number }}
    path: .sorry-delta-comment.md
```

**After:**

```yaml
- uses: Beneficial-AI-Foundation/veritooling/sorry-delta@v1
  with:
    base-manifest: artifacts/sorry-manifest-base.txt
    head-manifest: artifacts/sorry-manifest.txt

- uses: Beneficial-AI-Foundation/veritooling/verification-delta-report@v1
  with:
    sorry-delta-path: .sorry-delta-section.md

- uses: marocchino/sticky-pull-request-comment@v2
  with:
    header: verification-delta
    number: ${{ steps.pr.outputs.number }}
    path: .verification-delta-comment.md
```

### Step 3: Delete local scripts

Remove `scripts/Audit.lean` and `scripts/sorry-diff.py` from your repository.

## Composing Actions Directly

For maximum flexibility, use the individual actions in your own workflow
instead of the reusable workflows.

### Build job (pull_request trigger)

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: leanprover/lean-action@v1
        with:
          build: true

      # Restore baseline
      - uses: actions/cache/restore@v4
        if: github.event_name == 'pull_request'
        with:
          key: sorry-manifest-${{ github.event.pull_request.base.ref }}-${{ github.event.pull_request.base.sha }}
          restore-keys: sorry-manifest-main-
          path: sorry-manifest.txt

      - if: github.event_name == 'pull_request'
        run: '[ -f sorry-manifest.txt ] && mv sorry-manifest.txt sorry-manifest-base.txt || true'
        shell: bash

      # Generate sorry manifest
      - uses: Beneficial-AI-Foundation/veritooling/sorry-audit-probe@v1

      # Save baseline on main push
      - uses: actions/cache/save@v4
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        with:
          key: sorry-manifest-main-${{ github.sha }}
          path: sorry-manifest.txt

      # Specs delta (optional)
      - uses: Beneficial-AI-Foundation/veritooling/specs-delta@v1
        if: github.event_name == 'pull_request'
        with:
          mode: git-diff
          specs-paths: MyProject/Specs
          base-ref: ${{ github.event.pull_request.base.sha }}

      # Upload for comment workflow
      - if: github.event_name == 'pull_request'
        run: echo "${{ github.event.pull_request.number }}" > pr-number.txt
        shell: bash

      - uses: actions/upload-artifact@v4
        if: github.event_name == 'pull_request'
        with:
          name: verification-audit
          path: |
            sorry-manifest.txt
            sorry-manifest-base.txt
            specs-delta.json
            .specs-delta-section.md
            pr-number.txt
          if-no-files-found: ignore
          retention-days: 1
```

### Comment job (workflow_run trigger)

```yaml
name: Verification Comment
on:
  workflow_run:
    workflows: ["My Build Workflow"]
    types: [completed]

jobs:
  comment:
    if: >-
      github.event.workflow_run.event == 'pull_request' &&
      github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      actions: read
    steps:
      - uses: actions/checkout@v4
        with:
          repository: Beneficial-AI-Foundation/veritooling
          sparse-checkout: |
            sorry-delta/
            verification-delta-report/

      - uses: actions/download-artifact@v4
        with:
          name: verification-audit
          path: artifacts
          run-id: ${{ github.event.workflow_run.id }}
          github-token: ${{ secrets.GITHUB_TOKEN }}

      - id: pr
        run: |
          PR_NUM=$(cat artifacts/pr-number.txt)
          if ! [[ "$PR_NUM" =~ ^[0-9]+$ ]]; then
            echo "::error::Invalid PR number: $PR_NUM"
            exit 1
          fi
          echo "number=$PR_NUM" >> "$GITHUB_OUTPUT"
        shell: bash

      - uses: ./sorry-delta
        with:
          base-manifest: artifacts/sorry-manifest-base.txt
          head-manifest: artifacts/sorry-manifest.txt

      - uses: ./verification-delta-report
        with:
          sorry-delta-path: .sorry-delta-section.md
          specs-delta-path: artifacts/.specs-delta-section.md

      - uses: marocchino/sticky-pull-request-comment@v2
        with:
          header: verification-delta
          number: ${{ steps.pr.outputs.number }}
          path: .verification-delta-comment.md
```

# sorry-audit

One-step sorry-audit pipeline for the build job. Restores the base branch's
manifest, generates the head manifest with your chosen backend, caches it on the
default branch, optionally runs the specs delta, and uploads the artifacts the
verification-comment workflow reads — all in a single step you can drop into a
job that also does other things (e.g. a doc-site build).

This is the orchestration layer; the actual sorry detection is delegated to
[`sorry-audit-collectaxioms`](../sorry-audit-collectaxioms/) or
[`sorry-audit-probe`](../sorry-audit-probe/), and spec-change detection to
[`specs-delta`](../specs-delta/). The reusable
[`lean-build-audit.yml`](../../.github/workflows) workflow is just `checkout` +
`lake build` + this action.

## Usage

```yaml
- uses: leanprover/lean-action@v1
  with:
    build: true

- uses: Beneficial-AI-Foundation/veritooling/actions/sorry-audit@v1
  with:
    backend: collectaxioms      # or `probe` (default, zero-config)
    root-module: MyProject      # collectaxioms only; auto-detected if omitted
```

Use it directly (rather than the reusable workflow) when the audit shares a job
with other steps — for example building docs from the same `lake build`.

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `backend` | `probe` | `collectaxioms` or `probe` |
| `root-module` | `""` | Roots for `collectaxioms`; auto-detected from `lakefile.toml` if empty |
| `exclude-module` | `""` | Modules to omit from the detailed audit (`collectaxioms`) |
| `specs-delta-mode` | `off` | `off` or `git-diff` |
| `specs-paths` | `""` | Specs directory paths (`git-diff` mode) |
| `manifest-path` | `sorry-manifest.txt` | Generated head manifest path |
| `artifact-name` | `verification-audit` | Uploaded artifact bundle name |

## Outputs

| Output | Description |
|--------|-------------|
| `sorry-count` | Total sorry-tainted declaration count |

## Behaviour by event

- **`pull_request`**: restores the base manifest, runs the audit, runs the specs
  delta (if enabled), and uploads `verification-audit` for the comment job.
- **`push` to the default branch**: runs the audit and caches the manifest as the
  new baseline.

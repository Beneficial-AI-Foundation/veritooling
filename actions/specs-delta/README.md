# specs-delta

Detect which specification theorems a PR added, removed, or changed.

## Modes

### `git-diff` (lightweight)

Detects file-level changes in specs directories using `git diff --name-status`.
No external tools required.

```yaml
- uses: Beneficial-AI-Foundation/veritooling/actions/specs-delta@v1
  with:
    mode: git-diff
    specs-paths: MyProject/Specs
    base-ref: ${{ github.event.pull_request.base.sha }}
```

### `probe` (declaration-level)

Diffs probe-lean JSON outputs to detect declaration-level spec changes,
including verification status transitions (newly verified, newly broken).

```yaml
- uses: Beneficial-AI-Foundation/veritooling/actions/specs-delta@v1
  with:
    mode: probe
    probe-base-json: probe-base.json
    probe-head-json: probe-head.json
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `mode` | no | `git-diff` | Detection mode |
| `specs-paths` | git-diff only | -- | Comma-separated specs directory paths |
| `base-ref` | git-diff only | -- | Base git ref |
| `probe-base-json` | probe only | -- | Base probe-lean JSON path |
| `probe-head-json` | probe only | -- | Head probe-lean JSON path |
| `output-path` | no | `specs-delta.json` | JSON output path |
| `markdown-output` | no | `.specs-delta-section.md` | Markdown output path |

## Outputs

| Output | Description |
|--------|-------------|
| `output-path` | Path to specs-delta.json |
| `markdown-path` | Path to specs-delta markdown section |
| `changed-count` | Number of spec changes |

## Output Format

`specs-delta.json` structure:

```json
{
  "mode": "git-diff",
  "count": 2,
  "changes": [
    {"file": "MyProject/Specs/Foo.lean", "status": "modified"},
    {"file": "MyProject/Specs/Bar.lean", "status": "added"}
  ]
}
```

For probe mode, each change entry includes `declaration`, `module`,
`status`, and `verification-status` fields.

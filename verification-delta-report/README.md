# verification-delta-report

Combine sorry-delta and specs-delta markdown sections into a single
**Verification Delta** comment file for posting on a PR.

## Usage

```yaml
- uses: Beneficial-AI-Foundation/veritooling/verification-delta-report@v1
  with:
    sorry-delta-path: .sorry-delta-section.md
    specs-delta-path: .specs-delta-section.md  # optional
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `sorry-delta-path` | no | `.sorry-delta-section.md` | Sorry delta markdown |
| `specs-delta-path` | no | `""` | Specs delta markdown (empty to skip) |
| `output-path` | no | `.verification-delta-comment.md` | Combined output |

## Outputs

| Output | Description |
|--------|-------------|
| `comment-path` | Path to the combined comment file |

## Output Format

The combined file has this structure:

```markdown
### Verification Delta

#### Sorry Delta
(sorry delta content)

#### Specs Delta
(specs delta content, if provided)
```

Post the resulting file as a sticky PR comment:

```yaml
- uses: marocchino/sticky-pull-request-comment@v2
  with:
    header: verification-delta
    number: ${{ steps.pr.outputs.number }}
    path: .verification-delta-comment.md
```

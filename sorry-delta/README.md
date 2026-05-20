# sorry-delta

Compute the sorry-tainted declaration delta between a base and head manifest,
producing a markdown section for a PR comment.

## Usage

```yaml
- uses: Beneficial-AI-Foundation/veritooling/sorry-delta@v1
  with:
    base-manifest: sorry-manifests/sorry-manifest-base.txt
    head-manifest: sorry-manifests/sorry-manifest.txt
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `base-manifest` | yes | -- | Path to base manifest (may not exist) |
| `head-manifest` | yes | -- | Path to head manifest |
| `fail-on-new` | no | `false` | Exit with error if new sorries found |
| `output-path` | no | `.sorry-delta-section.md` | Output markdown path |

## Outputs

| Output | Description |
|--------|-------------|
| `new-count` | Number of new sorry-tainted declarations |
| `removed-count` | Number of removed sorry-tainted declarations |
| `total-count` | Total sorry-tainted declarations in head |
| `comment-path` | Path to the generated markdown section |

## Manifest Format

The sorry manifest is a versioned text file:

```
# sorry-manifest v1
ModuleName declaration.name direct
ModuleName another.declaration transitive
```

- First line: `# sorry-manifest v1` (version header, required)
- Each subsequent line: `<Module> <Declaration> <direct|transitive>`
- Sorted lexicographically
- Declaration name (column 2) is the identity key

## Security

This action performs pure computation: it reads two text files and writes a
markdown file. It needs no permissions beyond file system access. Run it in the
`workflow_run`-triggered job alongside `verification-delta-report`.

# sorry-delta

Compute the sorry-tainted declaration delta between a base and head manifest,
producing a markdown section for a PR comment.

## Usage

```yaml
- uses: Beneficial-AI-Foundation/veritooling/actions/sorry-delta@v1
  with:
    base-manifest: sorry-manifests/sorry-manifest-base.txt
    head-manifest: sorry-manifests/sorry-manifest.txt
```

### Report only on hand-written code

Aeneas-style projects carry sorries in generated/extracted code that churn on
every regeneration. To avoid comment noise, set `include-prefix` to the
hand-written module prefix(es): the delta and the `should-comment` signal then
cover only those modules.

```yaml
- uses: Beneficial-AI-Foundation/veritooling/actions/sorry-delta@v1
  id: sorry
  with:
    base-manifest: sorry-manifests/sorry-manifest-base.txt
    head-manifest: sorry-manifests/sorry-manifest.txt
    include-prefix: MyProject        # ignore sorries in e.g. Extracted.*
# gate the comment: steps.sorry.outputs.should-comment == 'true'
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `base-manifest` | yes | -- | Path to base manifest (may not exist) |
| `head-manifest` | yes | -- | Path to head manifest |
| `fail-on-new` | no | `false` | Exit with error if new sorries found (respects `include-prefix`) |
| `include-prefix` | no | `""` | Module prefix(es) to report on; comma/whitespace-separated. Empty reports on all modules |
| `output-path` | no | `.sorry-delta-section.md` | Output markdown path |

## Outputs

| Output | Description |
|--------|-------------|
| `new-count` | Number of new sorry-tainted declarations (within `include-prefix` if set) |
| `removed-count` | Number of removed sorry-tainted declarations |
| `total-count` | Total sorry-tainted declarations in head |
| `comment-path` | Path to the generated markdown section |
| `should-comment` | `"true"` when a comment is warranted (see `include-prefix`) |

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

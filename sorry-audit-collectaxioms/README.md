# sorry-audit-collectaxioms

Generate a sorry manifest using Lean's `collectAxioms` API for deep,
transitive axiom-closure analysis.

## What It Detects

- **`sorryAx`** in the transitive axiom closure (not just direct body usage)
- **`Lean.trustCompiler`** usage
- All non-builtin axioms (`propext`, `Classical.choice`, `Quot.sound` are filtered)
- BFS provenance tracing: which direct-sorry declaration contaminates which in-focus theorem

## Prerequisites

- `lake build` must have completed successfully before this action runs
- Every root module must be importable (all `.olean` files built)

## Usage

```yaml
- uses: leanprover/lean-action@v1
  with:
    build: true

- uses: Beneficial-AI-Foundation/veritooling/sorry-audit-collectaxioms@v1
  with:
    root-module: MyProject
```

By default the detailed audit covers every in-project module.  For a project
that keeps churn-heavy generated/extracted code in a separate top-level
library, list every root and exclude the generated one from the detailed view
(it is still scanned and still appears in the manifest):

```yaml
- uses: Beneficial-AI-Foundation/veritooling/sorry-audit-collectaxioms@v1
  with:
    root-module: MyProject,Extracted
    exclude-module: Extracted        # keep generated code out of the detailed audit
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `root-module` | yes | -- | Root module name(s) to scan; comma- or whitespace-separated for several (e.g. `MyProject` or `MyProject,Extracted`) |
| `exclude-module` | no | `""` | Module(s) to omit from the detailed audit (Sections 1 & 2); comma- or whitespace-separated. Excluded code is still scanned and still appears in the summary and manifest |
| `manifest-path` | no | `sorry-manifest.txt` | Output manifest path |

## Outputs

| Output | Description |
|--------|-------------|
| `manifest-path` | Path to the generated manifest |
| `sorry-count` | Total sorry-tainted declaration count |

## How It Works

1. Generates a Lean script from a parameterized template, substituting the
   root module name(s) and any excluded module(s)
2. Runs `lake env lean <script>` in the project environment
3. The script uses `Lean.collectAxioms` on every project declaration to find
   those whose transitive axiom closure includes `sorryAx`
4. Produces a `# sorry-manifest v1` file

# sorry-audit-collectaxioms

Generate a sorry manifest using Lean's `collectAxioms` API for deep,
transitive axiom-closure analysis.

## What It Detects

- **`sorryAx`** in the transitive axiom closure (not just direct body usage)
- **`Lean.trustCompiler`** usage
- All non-builtin axioms (`propext`, `Classical.choice`, `Quot.sound` are filtered)
- BFS provenance tracing: which direct-sorry declaration contaminates which spec theorem

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
    specs-prefix: MyProject.Specs   # optional
```

To audit a project that keeps extracted code in a separate top-level
library, list every root (comma- or whitespace-separated):

```yaml
- uses: Beneficial-AI-Foundation/veritooling/sorry-audit-collectaxioms@v1
  with:
    root-module: MyProject,Extracted
    specs-prefix: MyProject.Specs
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `root-module` | yes | -- | Root module name(s) to scan; comma- or whitespace-separated for several (e.g. `MyProject` or `MyProject,Extracted`) |
| `specs-prefix` | no | `""` | Specs module prefix for detailed audit sections |
| `manifest-path` | no | `sorry-manifest.txt` | Output manifest path |

## Outputs

| Output | Description |
|--------|-------------|
| `manifest-path` | Path to the generated manifest |
| `sorry-count` | Total sorry-tainted declaration count |

## How It Works

1. Generates a Lean script from a parameterized template, substituting the
   root module name(s) and specs prefix
2. Runs `lake env lean <script>` in the project environment
3. The script uses `Lean.collectAxioms` on every project declaration to find
   those whose transitive axiom closure includes `sorryAx`
4. Produces a `# sorry-manifest v1` file

## Security

This action runs `lake env lean` on a generated Lean script. It should only
run after a trusted `lake build` step. The generated script is deterministic
(no user-controlled content beyond the module name inputs) and is cleaned up
after execution.

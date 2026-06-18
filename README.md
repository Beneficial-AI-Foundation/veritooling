# veritooling

Reusable CI toolkit for Lean 4 verification projects. Track `sorry`-tainted
declarations, detect specification changes, and surface verification deltas as
PR comments — without copying scripts into every repo.

## Workflows

| Workflow | Purpose |
|----------|---------|
| [`lean-build-audit.yml`](.github/workflows/lean-build-audit.yml) | Build a Lean project and generate sorry/axiom audit artifacts. |
| [`verification-comment.yml`](.github/workflows/verification-comment.yml) | Post the verification-delta PR comment from those artifacts. |

See [`.github/workflows/README.md`](.github/workflows/README.md) for how the
reports are generated and how to wire these into your project. More workflows
will be added over time.

## Actions

The workflows compose these self-contained composite actions; you can also use
them individually.

| Action | Phase | Purpose |
|--------|-------|---------|
| [`sorry-audit-collectaxioms`](actions/sorry-audit-collectaxioms/) | Generation | Transitive axiom-closure sorry detection via Lean metaprogramming. |
| [`sorry-audit-probe`](actions/sorry-audit-probe/) | Generation | Sorry detection via [probe-lean](https://github.com/Beneficial-AI-Foundation/probe-lean). |
| [`specs-delta`](actions/specs-delta/) | Generation | Detect specification-theorem changes. |
| [`sorry-delta`](actions/sorry-delta/) | Reporting | Diff sorry manifests and format the delta. |
| [`verification-delta-report`](actions/verification-delta-report/) | Reporting | Combine deltas into one PR comment. |

## License

Apache-2.0

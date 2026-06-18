# Actions

Composite actions, each usable on its own as
`Beneficial-AI-Foundation/veritooling/actions/<name>@v1`. Most projects don't
call these directly — they use the reusable workflows in
[`.github/workflows`](../.github/workflows), which compose them. See that
folder's README for how the pieces fit together.

| Action | Phase | Purpose |
|--------|-------|---------|
| [`sorry-audit`](sorry-audit/) | Generation | One-step pipeline: restore baseline, audit, cache, specs delta, upload. Composes the actions below. |
| [`sorry-audit-collectaxioms`](sorry-audit-collectaxioms/) | Generation | Transitive axiom-closure sorry detection via Lean metaprogramming. |
| [`sorry-audit-probe`](sorry-audit-probe/) | Generation | Sorry detection via [probe-lean](https://github.com/Beneficial-AI-Foundation/probe-lean). |
| [`specs-delta`](specs-delta/) | Generation | Detect specification-theorem changes. |
| [`sorry-delta`](sorry-delta/) | Reporting | Diff sorry manifests and format the delta. |
| [`verification-delta-report`](verification-delta-report/) | Reporting | Combine deltas into one PR comment. |

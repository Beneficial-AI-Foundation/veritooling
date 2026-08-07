# How the leanblueprint numbers are computed

How `progress_history.py --pipeline leanblueprint` turns a Lean blueprint project
(e.g. secure-messaging) into the per-commit numbers behind the burn-up chart.

## 1. Get the data (per commit, in the work-clone)

For each sampled commit the tool checks out the commit, selects the
`probe-lean-v<toolchain>` matching its `lean-toolchain` (probe-lean reads
`.olean`s, whose format is version-specific), and runs `probe-leanblueprint
extract`. That extract does three things:

1. **`probe-lean extract`** analyzes every Lean module and emits **atoms**, each
   with a machine `verification-status` (does it elaborate, is it sorry-free).
2. **Verso blueprint render** (for secure-messaging via
   `scripts/render-docs-site.sh`) produces per-chapter `blueprint-manifest.json`
   under `_out/site`. This is the **blueprint graph**: one node per
   `definition`/`theorem` entry, each carrying a two-axis status.
3. **Join** binds blueprint nodes onto probe-lean atoms, emitting a Schema-3.0
   extract envelope where each node has `blueprint-*` fields.

The two axes (from probe-leanblueprint's `docs/SCHEMA.md`):

| axis | values | meaning |
|------|--------|---------|
| statement | `none`, `blocked`, `ready`, `formalized` | is the statement written in Lean? |
| proof | `none`, `ready`, `proved`, `fully-proved` | is the proof complete (sorry-free)? |

## 2. Count the numbers

`blueprint_progress.count_blueprint()` reads that envelope, groups atoms by
`blueprint-label` into one record per node (kind, statement status, proof status,
whether it is bound to a real Lean decl), and computes:

| Metric | Definition |
|--------|------------|
| **Total** | every blueprint node (`bound` + `planned-only` + `decl-missing`) |
| **Formalized** | nodes with `statement-status == "formalized"`, the Lean statement or signature exists |
| **Proved (probe-lean-confirmed)** | theorem nodes with `proof-status == "fully-proved"` and probe-lean-confirmed (bound, whole binding present, not contradicted by probe-lean) |

split into definitions vs theorems by node kind. The two axes come from the
blueprint; probe-lean's own `verification-status` is what makes "proved"
probe-lean-confirmed rather than the bare blueprint claim. `bp_thm_proved` keeps
the claim; `bp_thm_proved_confirmed` is the confirmed number, matching
probe-leanblueprint's own `theorems-fully-proved-probe-lean-confirmed`.

The `Total` buckets:

- **bound**: node bound to a real probe-lean decl.
- **planned-only**: a blueprint node with no decl at all (a pure stub).
- **decl-missing**: the blueprint claims a decl probe-lean cannot find (an
  over-claim).

Worked example, **2026-07-22**: 114 nodes total; of 58 definition nodes, 28 have
their Lean statement written; of 56 theorem nodes, 9 are stated and 9 have
complete, probe-lean-confirmed sorry-free proofs.

We count all blueprint nodes, deliberately not copying secure-messaging's site
convention of counting only atoms with a `{githubIssue …}` footer (that overlay
hides about 11 helper atoms and is specific to that repo). Terminology is
axis-explicit (`Formalized`, `Proved`) rather than the site's overloaded
"specified": `Formalized` means the statement is written, and the
definition/theorem difference is carried by theorems having a second milestone
(`Proved`) that definitions lack.

## Default chart (`plot_progress.py`)

The `--split` two-panel chart keys definitions and theorems off the **blueprint**
axes. The default chart instead pools every node into one panel and takes the proof
status from **probe-lean**, in the three-category vocabulary. Each formalized
node's bound-atom `verification-status` values roll up to one node status by
worst-status precedence:

```
failed  >  unverified  >  trusted  >  {verified, transitively-verified}
```

matching `colors.py`: `verified` and `transitively-verified` are both green, and
`trusted` (axiom/external) dominates green, so any trust reliance keeps a node out
of strict `verified`. Every node then lands in exactly one bucket:

| bucket | meaning |
|--------|---------|
| **unspecified** | statement not `formalized` (no Lean statement yet) |
| **unrealized** | `formalized` but no bound atom carrying a machine status (a decl-missing over-claim, or a shadow binding) |
| **in-progress** | `formalized`, a bound atom is `unverified` (a `sorry`) |
| **failed** | `formalized`, a bound atom `failed` to elaborate |
| **verified** | `formalized`, all bound atoms green |
| **verified + trusted** | the `verified` bucket plus nodes whose rollup is `trusted` |

Per kind, `verified + trusted + in_progress + failed + unrealized` equals
`formalized`, and `unspecified` is `total − formalized`. The chart's `completed`
category is `verified + trusted`, summed over definitions and theorems; `tracked`
is the node total, `in-progress` the bucket above. The `trusted` slice of that sum
is what `--trusted` draws, and `unspecified` / `failed` / `unrealized` are the
remaining opt-in overlays.

Two caveats. Trust is detected only within a node's own bindings, so a green node
depending on an axiom in another node still reads `verified` (a full fix needs a
`collectAxioms`-style transitive walk). And the chart measures blueprint
completion, not repo-wide sorry debt: `in-progress` counts only formalized
blueprint nodes whose bindings hold a `sorry`. A `sorry` in a declaration the
blueprint does not track (e.g. secure-messaging's `PRFPRNG` work in progress, 10
sorry decls including a `security` theorem, none bound to a blueprint node) is
invisible, so `in-progress = 0` is not "no sorries in the repo". Surfacing that is
[#34](https://github.com/Beneficial-AI-Foundation/veritooling/issues/34).

## Reproduce a single point

Straight from any extract JSON, independent of the history tool:

```bash
python3 blueprint_progress.py <path>/leanblueprint_SecureMessaging_<sha>.json --table
```

This recomputes everything from the `blueprint-*` fields (stdlib only), so it
also cross-checks probe-leanblueprint's own summary sidecar.

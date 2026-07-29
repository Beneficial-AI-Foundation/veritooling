# How the leanblueprint numbers are computed

How `progress_history.py --pipeline leanblueprint` turns a Lean blueprint project
(e.g. secure-messaging) into the per-commit numbers behind the burn-up chart.

## 1. Get the data (per commit, in the work-clone)

For each sampled commit the tool:

1. Checks out the commit and selects `probe-lean-v<toolchain>` matching its
   `lean-toolchain` — probe-lean reads `.olean`s, whose format is
   Lean-version-specific, so the binary must match the target.
2. Runs `probe-leanblueprint extract`, which does three things:
   - **`probe-lean extract`** — analyzes every Lean module and emits **atoms**,
     each with a machine `verification-status` (does it elaborate / is it
     sorry-free).
   - **Verso blueprint render** — for secure-messaging via
     `scripts/render-docs-site.sh`, producing per-chapter
     `blueprint-manifest.json` under `_out/site`. This is the **blueprint
     graph**: one node per `definition`/`theorem` entry, each carrying a
     **two-axis status**.
   - **Join** — binds blueprint nodes onto the probe-lean atoms, emitting a
     Schema-3.0 extract envelope where each node has `blueprint-*` fields.

The two axes (from `probe-leanblueprint`'s `docs/SCHEMA.md`):

| axis | values | meaning |
|------|--------|---------|
| statement | `none` → `blocked` → `ready` → `formalized` | is the statement written in Lean? |
| proof | `none` → `ready` → `proved` → `fully-proved` | is the proof complete (sorry-free)? |

## 2. Count the numbers

`blueprint_progress.count_blueprint()` reads that envelope, groups atoms by
`blueprint-label` into one record per node (kind, statement-status,
proof-status, whether it is bound to a real Lean decl), and computes:

| Metric | Definition |
|--------|------------|
| **Total** | every blueprint node (`bound` + `planned-only` + `decl-missing`) |
| **Formalized** | nodes with `statement-status == "formalized"` — the Lean statement/signature exists |
| **Proved (probe-lean-confirmed)** | theorem nodes with `proof-status == "fully-proved"` **and** probe-lean-confirmed (bound, whole binding present, not contradicted by probe-lean) |

split into **definitions** vs **theorems** by node kind. The two axes come from
the blueprint; probe-lean's own `verification-status` is what makes "proved"
*probe-lean-confirmed* rather than merely the blueprint's claim (`bp_thm_proved`
keeps the bare claim; `bp_thm_proved_confirmed` is the honest, probe-lean-confirmed
number — probe-leanblueprint's `theorems-fully-proved-probe-lean-confirmed`).

Node buckets underlying `Total`:

- **bound** — node bound to a real probe-lean decl (a.k.a. `with-lean-decl`),
- **planned-only** — a blueprint node with no decl at all (a pure stub),
- **decl-missing** — the blueprint claims a decl probe-lean cannot find (an
  over-claim).

Worked example — **2026-07-22**: 114 nodes total; of the 58 definition nodes, 28
have their Lean statement written (formalized); of the 56 theorem nodes, 9 are
stated and 9 have complete, probe-lean-confirmed sorry-free proofs.

## Which nodes count, and the terminology

- **We count all blueprint nodes.** We deliberately did *not* copy
  secure-messaging's site convention of counting only atoms carrying a
  `{githubIssue …}` footer — that overlay just hides ~11 helper atoms
  (oracle/advantage scaffolding) and is specific to that repo.
- **Terminology is axis-explicit** (`Formalized` / `Proved`), replacing the
  published site's overloaded "specified". `Formalized` now has one
  meaning (statement written); the definition/theorem difference is carried by
  theorems having a second milestone (`Proved`) that definitions lack.

## Combined-atoms chart (`plot_progress.py --atoms`)

The two-panel chart above keys definitions and theorems off the **blueprint**
axes. The combined chart instead puts every node in one atom pool and takes the
proof status from **probe-lean**, using the FC ("Atom statuses and colours")
vocabulary. Each formalized node's bound-atom `verification-status` values are
rolled up to one node status by worst-status precedence:

```
failed  >  unverified  >  trusted  >  {verified, transitively-verified}
```

matching `colors.py` (`verified` and `transitively-verified` are both green;
`trusted` — axiom/external — dominates green so any trust reliance keeps a node
out of strict `verified`). Every node then lands in exactly one bucket:

| bucket | meaning |
|--------|---------|
| **unspecified** | statement not `formalized` (no Lean statement yet) |
| **unrealized** | `formalized` but no bound decl (a planned/decl-missing over-claim) |
| **in-progress** | `formalized`, a bound atom is `unverified` (a `sorry`) |
| **failed** | `formalized`, a bound atom `failed` to elaborate |
| **verified** | `formalized`, all bound atoms green (verified / transitively-verified) |
| **verified + trusted** | the `verified` bucket plus nodes whose rollup is `trusted` |

Per kind, `verified + trusted + in_progress + failed + unrealized` equals
`formalized`; `unspecified` is `total − formalized`. The plotted `verified` and
`verified + trusted` series sum def and thm together.

Two caveats. (1) Trust is detected only within a node's own bindings, so a green
node depending on an axiom in another node still reads `verified` (a full fix
needs a `collectAxioms`-style transitive walk; see the plan). (2) The chart
measures **blueprint completion**, not repo-wide sorry debt: `in-progress` counts
only formalized blueprint nodes whose bindings hold a `sorry`. A `sorry` in a
declaration the blueprint does not track — e.g. secure-messaging's `PRFPRNG` WIP
(10 sorry decls incl. a `security` theorem, none bound to a blueprint node) — is
invisible, so `in-progress = 0` is not "no sorries in the repo". Surfacing that
is [#34](https://github.com/Beneficial-AI-Foundation/veritooling/issues/34).
Rationale and review trail: `combined-atoms-plan.md`.

## Reproduce a single point

Straight from any extract JSON, independent of the history tool:

```bash
python3 blueprint_progress.py <path>/leanblueprint_SecureMessaging_<sha>.json --table
```

This recomputes everything from the `blueprint-*` fields (stdlib only), so it
also cross-checks `probe-leanblueprint`'s own summary sidecar.

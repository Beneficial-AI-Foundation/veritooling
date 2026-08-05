# data/verso-comparison

Artifacts for [`../../guides/verso-blueprint-comparison.md`](../../guides/verso-blueprint-comparison.md):
our dependency-graph + insights output beside verso-blueprint's own published
pages, for its four reference blueprints, each at the exact upstream commit verso
pins. This file says how every committed artifact was produced.

Five committed files per project (`carleson`, `sphere-packing`, `flt`,
`noperthedron`), plus `capture_verso_screenshots.py`:

| File | Produced by |
|------|-------------|
| `<proj>.ours-depgraph.svg` | `plot_depgraph.py <extract> -o <proj>.ours-depgraph.svg` |
| `<proj>.ours-depgraph.png` | `plot_depgraph.py <extract> --format png -o <proj>.ours-depgraph.png` |
| `<proj>.ours-insights.txt` | `blueprint_insights.py <extract> --manifest <manifest> --table > <proj>.ours-insights.txt` |
| `<proj>.verso-summary-overview.png` | `capture_verso_screenshots.py` (element shot of the Overview card) |
| `<proj>.verso-depgraph.png` | `capture_verso_screenshots.py` (full-page shot of the d3 graph) |

`<extract>` and `<manifest>` come from the steps below. The extract envelope
itself is **not committed** (it needs a built Lean project and is large).

## Pinned inputs

verso pins each reference blueprint through an `ejgallego/verso-<proj>` wrapper
repo (catalog: `leanprover/verso-blueprint:tests/harness/projects.json`); the
wrapper's git submodule fixes the upstream math-project commit. Our extract runs
against a clone of that wrapper at the same SHA, so both sides are the same
commit.

| Project | Wrapper (`ejgallego/…`) @ SHA | Upstream submodule @ SHA | Lean |
|---------|-------------------------------|--------------------------|------|
| carleson | `verso-carleson` @ `5b34f5d4` | `fpvandoorn/carleson` @ `8e93bee1` | v4.31.0 |
| sphere-packing | `verso-sphere-packing` @ `4cbb43d6` | `thefundamentaltheor3m/Sphere-Packing-Lean` @ `1828993f` | v4.31.0 |
| flt | `verso-flt` @ `1695b7cb` | `ImperialCollegeLondon/FLT` @ `ee47fd2a` | v4.32.0-rc1 |
| noperthedron | `verso-noperthedron` @ `ad062f0d` | `jcreedcmu/Noperthedron` @ `83502054` | v4.32.0-rc1 |

## Reproduce

**1. Build the wrapper clone** (submodules checked out, `lake exe cache get` so
Mathlib is not compiled, docs rendered so `blueprint-manifest.json` exists under
`_out/site/html-multi/-verso-data/`). This is the expensive step; the rest are
seconds each.

**2. Extract** (reads the built oleans + existing manifest; `--no-render`):

```bash
MAN=<wrapper-clone>/_out/site/html-multi/-verso-data/blueprint-manifest.json
probe-leanblueprint extract <wrapper-clone> --no-render --verso-manifest "$MAN" \
  -o /tmp/<proj>.extract.json                 # add --summary-output for the sidecar
```

**3. Our graph + insights** (run from the tool directory):

```bash
python3 plot_depgraph.py      /tmp/<proj>.extract.json -o <proj>.ours-depgraph.svg
python3 plot_depgraph.py      /tmp/<proj>.extract.json --format png -o <proj>.ours-depgraph.png
python3 blueprint_insights.py /tmp/<proj>.extract.json --manifest "$MAN" --table > <proj>.ours-insights.txt
```

**4. verso screenshots** (needs Playwright + Chromium, see the script header):

```bash
python3 capture_verso_screenshots.py
```

## Caveats

- The `machine` column in `*.ours-insights.txt` and the solid-green nodes in
  `*.ours-depgraph.*` are degenerate here: the extract runs against the verso
  **wrapper** project, whose modules are the blueprint document, not the upstream
  Lean library, so probe-lean cannot bind blueprint nodes to their declarations
  (`decl-missing`). This does not affect the claimed-vs-verso comparison (verso
  has no machine column). See the guide's "Graph coloring" section.
- verso's summary counts are server-rendered (exact reads); its dependency graph
  is a d3 rendering, so the screenshot depends on that JS having run.

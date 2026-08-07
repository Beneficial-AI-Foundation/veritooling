# dashboard-poc

Proof of concept: the burn-up history we already collect (`data/<project>/progress.csv`)
can drive a **dynamic, multi-plot dashboard** — hover, zoom, legend toggling,
light/dark — with no server and no database. One self-contained HTML file you
open in any browser or hand to someone.

## Why not Apache Superset

The original ask was a Superset demo. Loading a CSV into SQL is the *easy* part
(Superset has an upload button; `df.to_sql(...)` is one line). The cost is
standing up Superset itself — a multi-container stack (web, worker, redis,
metadata DB). For "show that we could have dynamic dashboards with all sorts of
plots," that's overkill. This POC gets the same demo value from a single file.
Superset still makes sense later if you want its SQL-backed, point-and-click
chart builder and shared saved dashboards.

## Run

```bash
python3 build_dashboard.py                       # dalek-verus -> index.html
python3 build_dashboard.py ../data/secure-messaging/progress.csv -o sm.html
open index.html                                  # any browser; needs internet for the Plotly CDN
```

Standard library only, Python 3.10+. Plotly is pulled from a CDN by the page.

## Plots (dalek-verus)

- **Burn-up** — the three categories, matching the static `burnup.svg`: completed
  climbing toward the tracked ceiling, with in-progress alongside.
- **Completion** — completed as a share of tracked code (%), beside the verified
  share, so the axiom-backed gap between them is visible.
- **Exec-atom status composition** — stacked area of the atom-status buckets
  over time (unspecified → in-progress → trusted → verified).
- **Verification artifacts checked** — accepted / unverified / failed specs and
  proofs per sample.
- **Run health** — sampling-run duration; a failed run shows red (reason on hover).

Status colours are the fixed VeriLib atom-status palette (see `../colors.py`);
metric charts use only successful sampling runs, Run health shows every run.

`index.html` is a generated artifact — re-run `build_dashboard.py` to refresh it.

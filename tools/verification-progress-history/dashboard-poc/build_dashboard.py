#!/usr/bin/env python3
"""Build a self-contained interactive dashboard from a progress-history CSV.

POC: demonstrates that the burn-up history we already collect can drive a
dynamic, multi-plot dashboard (hover, zoom, legend toggling, range select,
light/dark) with no server and no database -- just one HTML file you can open
or share. Reads a ``progress.csv`` produced by ``progress_history.py`` and
emits an ``index.html`` that embeds the data as JSON and renders it with
Plotly from a CDN.

The status colours are the fixed VeriLib atom-status palette (see
``../colors.py`` and the engineering docs), used verbatim so the dashboard
reads the same as the static ``burnup.svg``.

Usage:
    build_dashboard.py [CSV] [-o OUT]
    build_dashboard.py                       # defaults to dalek-verus data
    build_dashboard.py ../data/dalek-verus/progress.csv -o index.html

Standard library only, Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CSV = HERE / ".." / "data" / "dalek-verus" / "progress.csv"

# Fixed atom-status palette (hex from the engineering-docs scheme; mirrors the
# values in ../plot_progress.py). Semantic, not a free categorical choice.
COL = {
    "tracked": "#888899",  # neutral ceiling
    "verified_trusted": "#7B64B8",  # purple -- completion frontier
    "verified": "#1F8A65",  # green -- proved frontier
    "grey": "#B8B8C4",  # untracked / out of verification scope
    "white": "#B08D57",  # unspecified (tracked, no spec yet)
    "red": "#C0392B",  # failed
    "yellow": "#E8833A",  # in-progress (sorry / assume)
    "light_green": "#1F8A65",  # verified
    "dark_green": "#14664A",  # transitively-verified
    "purple": "#7B64B8",  # trusted
}

# Integer columns we want available client-side.
INT_COLS = [
    "grey",
    "white",
    "red",
    "yellow",
    "light_green",
    "dark_green",
    "purple",
    "exec_total",
    "dot_red",
    "dot_yellow",
    "dot_green",
    "art_total",
    "tracked",
    "verified",
    "verified_trusted",
    "translated",
]


def load_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        rec = {
            "sample_date": r["sample_date"],
            "commit": r.get("commit", "")[:9],
            "commit_date": r.get("commit_date", ""),
            "status": r.get("status", ""),
            "reason": r.get("reason", ""),
            "duration_sec": float(r["duration_sec"]) if r.get("duration_sec") else None,
        }
        for c in INT_COLS:
            rec[c] = int(r[c]) if r.get(c) not in (None, "") else 0
        out.append(rec)
    out.sort(key=lambda x: x["sample_date"])
    return out


def build_html(rows: list[dict], repo: str) -> str:
    dates = [r["sample_date"] for r in rows]
    payload = {
        "repo": repo,
        "rows": rows,
        "col": COL,
        "span": f"{dates[0]} to {dates[-1]}" if dates else "",
    }
    data_json = json.dumps(payload)
    return _TEMPLATE.replace("__DATA__", data_json).replace("__REPO__", repo)


_TEMPLATE = r"""<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__REPO__ - verification progress</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  :root {
    --bg: #f6f6f8; --surface: #ffffff; --ink: #23232b; --muted: #6b6b76;
    --border: #e4e4ea; --grid: rgba(60,60,80,.10);
  }
  html[data-theme="dark"] {
    --bg: #14141a; --surface: #1e1e26; --ink: #e9e9f0; --muted: #9a9aa6;
    --border: #2c2c36; --grid: rgba(200,200,220,.12);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  header {
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
    padding: 20px 24px 8px;
  }
  header h1 { font-size: 20px; margin: 0; font-weight: 650; }
  header .sub { color: var(--muted); font-size: 13px; }
  header .spacer { flex: 1; }
  button.theme {
    border: 1px solid var(--border); background: var(--surface); color: var(--ink);
    border-radius: 8px; padding: 6px 12px; cursor: pointer; font: inherit;
  }
  .kpis { display: flex; gap: 12px; flex-wrap: wrap; padding: 8px 24px 4px; }
  .kpi {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 16px; min-width: 150px;
  }
  .kpi .v { font-size: 26px; font-weight: 680; letter-spacing: -.02em; }
  .kpi .l { color: var(--muted); font-size: 12px; margin-top: 2px; }
  .grid {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px; padding: 12px 24px 28px;
  }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px 12px 4px;
  }
  .card h2 { font-size: 14px; margin: 4px 6px 0; font-weight: 620; }
  .card p.hint { margin: 2px 6px 6px; color: var(--muted); font-size: 12px; }
  .plot { width: 100%; height: 300px; }
  footer { color: var(--muted); font-size: 12px; padding: 0 24px 28px; }
</style>
</head>
<body>
<header>
  <h1>__REPO__</h1>
  <span class="sub" id="span"></span>
  <span class="spacer"></span>
  <button class="theme" id="themeBtn">Dark mode</button>
</header>
<div class="kpis" id="kpis"></div>
<div class="grid">
  <div class="card"><h2>Burn-up</h2>
    <p class="hint">Verified & completion frontier climbing toward the tracked ceiling.</p>
    <div class="plot" id="burnup"></div></div>
  <div class="card"><h2>Verification frontier</h2>
    <p class="hint">Share of tracked code that is verified / verified+trusted.</p>
    <div class="plot" id="frontier"></div></div>
  <div class="card"><h2>Exec-atom status composition</h2>
    <p class="hint">How the tracked code base moved between statuses over time.</p>
    <div class="plot" id="composition"></div></div>
  <div class="card"><h2>Verification artifacts checked</h2>
    <p class="hint">Specs & proofs the tool accepted / flagged at each sample.</p>
    <div class="plot" id="artifacts"></div></div>
  <div class="card"><h2>Run health</h2>
    <p class="hint">Sampling-run duration; red marks a run the verifier could not complete.</p>
    <div class="plot" id="health"></div></div>
</div>
<footer id="footer"></footer>

<script>
const DATA = __DATA__;
const R = DATA.rows, C = DATA.col;
const ok = R.filter(r => r.status === "ok");
const x = ok.map(r => r.sample_date);
document.getElementById("span").textContent = DATA.span + "  -  " + R.length + " samples";

function themed() {
  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  const ink = dark ? "#e9e9f0" : "#23232b";
  const muted = dark ? "#9a9aa6" : "#6b6b76";
  const grid = dark ? "rgba(200,200,220,.14)" : "rgba(60,60,80,.10)";
  return {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: ink, size: 12 },
    margin: { l: 48, r: 16, t: 8, b: 36 },
    legend: { orientation: "h", y: -0.22, font: { size: 11 } },
    xaxis: { gridcolor: grid, linecolor: grid, tickfont: { color: muted } },
    yaxis: { gridcolor: grid, linecolor: grid, tickfont: { color: muted }, rangemode: "tozero" },
    hovermode: "x unified",
  };
}
const CFG = { responsive: true, displaylogo: false,
  modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] };

function line(name, y, color, dash) {
  return { x, y, name, mode: "lines+markers", type: "scatter",
    line: { color, width: 2, dash: dash || "solid" }, marker: { size: 6, color } };
}
function areaStack(name, y, color) {
  return { x, y, name, mode: "lines", type: "scatter", stackgroup: "s",
    line: { width: 0.5, color }, fillcolor: color };
}

// KPIs
const last = ok[ok.length - 1] || {};
const pct = last.tracked ? Math.round(100 * last.verified / last.tracked) : 0;
const pctT = last.tracked ? Math.round(100 * last.verified_trusted / last.tracked) : 0;
const kpis = [
  ["Verified", last.verified, "of " + last.tracked + " tracked"],
  ["Verified", pct + "%", "of tracked code"],
  ["Verified + trusted", pctT + "%", "completion frontier"],
  ["Artifacts checked", last.art_total, "specs & proofs"],
];
document.getElementById("kpis").innerHTML = kpis.map(k =>
  `<div class="kpi"><div class="v">${k[1]}</div>` +
  `<div class="l">${k[0]} - ${k[2]}</div></div>`).join("");

function draw() {
  const L = themed();
  Plotly.react("burnup", [
    line("tracked (ceiling)", ok.map(r => r.tracked), C.tracked, "dot"),
    line("verified + trusted", ok.map(r => r.verified_trusted), C.verified_trusted),
    line("verified", ok.map(r => r.verified), C.verified),
  ], { ...L, yaxis: { ...L.yaxis, title: { text: "exec atoms" } } }, CFG);

  const vtPct = ok.map(r => r.tracked ? 100 * r.verified_trusted / r.tracked : 0);
  const vPct = ok.map(r => r.tracked ? 100 * r.verified / r.tracked : 0);
  Plotly.react("frontier", [
    line("verified+trusted %", vtPct, C.verified_trusted),
    line("verified %", vPct, C.verified),
  ], { ...L, yaxis: { ...L.yaxis, title: { text: "% of tracked" }, range: [0, 100] } }, CFG);

  Plotly.react("composition", [
    areaStack("verified", ok.map(r => r.light_green), C.light_green),
    areaStack("transitively-verified", ok.map(r => r.dark_green), C.dark_green),
    areaStack("trusted", ok.map(r => r.purple), C.purple),
    areaStack("in-progress (sorry/assume)", ok.map(r => r.yellow), C.yellow),
    areaStack("failed", ok.map(r => r.red), C.red),
    areaStack("unspecified (no spec)", ok.map(r => r.white), C.white),
  ], { ...L, yaxis: { ...L.yaxis, title: { text: "tracked exec atoms" } } }, CFG);

  const bar = (y, name, color) => ({ x, y, name, type: "bar", marker: { color } });
  Plotly.react("artifacts", [
    bar(ok.map(r => r.dot_green), "accepted", C.light_green),
    bar(ok.map(r => r.dot_yellow), "unverified", C.yellow),
    bar(ok.map(r => r.dot_red), "failed", C.red),
  ], { ...L, barmode: "stack", yaxis: { ...L.yaxis, title: { text: "artifacts" } } }, CFG);

  // Run health includes error runs; colour by status.
  const hx = R.map(r => r.sample_date);
  const hcol = R.map(r => r.status === "ok" ? C.verified : C.red);
  const htext = R.map(r => r.status === "ok" ? "ok" : (r.reason || r.status));
  Plotly.react("health", [{
    x: hx, y: R.map(r => r.duration_sec), type: "bar",
    marker: { color: hcol }, text: htext, textposition: "none",
    hovertemplate: "%{x}<br>%{y:.1f}s<br>%{text}<extra></extra>",
  }], { ...L, hovermode: "closest", yaxis: { ...L.yaxis, title: { text: "seconds" } } }, CFG);
}
draw();

document.getElementById("themeBtn").addEventListener("click", () => {
  const el = document.documentElement;
  const dark = el.getAttribute("data-theme") === "dark";
  el.setAttribute("data-theme", dark ? "light" : "dark");
  document.getElementById("themeBtn").textContent = dark ? "Dark mode" : "Light mode";
  draw();
});
document.getElementById("footer").textContent =
  "POC - generated from data/" + DATA.repo + "/progress.csv by build_dashboard.py. " +
  "Metric-charts show only successful sampling runs; Run health shows all.";
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "csv", nargs="?", type=Path, default=DEFAULT_CSV, help="progress.csv (default: dalek-verus)"
    )
    ap.add_argument("-o", "--out", type=Path, default=HERE / "index.html", help="output HTML path")
    args = ap.parse_args(argv)

    if not args.csv.is_file():
        ap.error(f"CSV not found: {args.csv}")
    rows = load_rows(args.csv)
    repo = rows[0]["commit"] and Path(args.csv).parent.name or "project"
    html = build_html(rows, repo)
    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out}  ({len(rows)} samples, repo={repo})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

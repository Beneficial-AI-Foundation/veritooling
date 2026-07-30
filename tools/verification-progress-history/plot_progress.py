#!/usr/bin/env python3
"""Render a verification progress burn-up chart from a progress history file.

Reads the JSONL (or CSV) produced by ``progress_history.py`` and writes a
self-contained **SVG** — no third-party dependencies, Python 3 stdlib only, so
the chart is reproducible in-repo and reviewable as text.

Renders the **burn-up** defined in the VeriLib "Atom statuses and colours" doc,
section "Progress chart (burn-up over time)": nested cumulative frontiers
``tracked ≥ (verified + trusted) ≥ verified`` (plus ``translated`` for Aeneas),
the completion frontier closing on the ceiling at "done". By default the
frontier gap (white + yellow + red) is left implicit — but ``--in-progress``
adds the doc's ``in-progress`` atom status (``yellow``: an incomplete proof,
sorry / assume) as its own curve, and ``--unspecified`` adds ``white`` (tracked
but no spec written yet). These are two distinct states; the gap conflates them.
``red`` (a failed verification) is drawn automatically whenever any sample has
one — like ``translated``, it needs no flag, and stays off when nothing failed.

For a **leanblueprint** history (``pipeline == leanblueprint``) it instead draws
two stacked panels mirroring the published blueprint site — Definitions (total +
formalized) and Theorems (total + formalized + proved), where "proved" is the
probe-lean-confirmed count. The mode is auto-detected from the records.
``--combined`` overrides this with a single FC-style panel that pools definitions
and theorems (counted as blueprint nodes): nested ``tracked ≥ verified+trusted ≥
verified`` frontiers, plus in-progress / failed / unrealized / unspecified status
curves drawn when present.

Only ``status == ok`` samples are plotted; gaps (verify_error, timeout, …) are
skipped, matching how the frontier chart is defined.

Usage:
    plot_progress.py <progress.jsonl|.csv> [-o out.svg] [--title TITLE]
"""

from __future__ import annotations

import argparse
import csv as csvmod
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

# Scheme colours (hex from the engineering-docs palette; see "Atom statuses and
# colours"). Kept literal so the SVG is dependency-free and self-describing.
COL = {
    "tracked": "#888899",  # neutral ceiling
    "verified_trusted": "#7B64B8",  # purple — completion frontier
    "verified": "#1F8A65",  # green — proved frontier
    "translated": "#2E79B5",  # blue — Aeneas intermediate
    "in_progress": "#E8833A",  # amber — in-progress (yellow: sorry / assume)
    "unspecified": "#B08D57",  # tan — tracked but no spec written yet (white)
    "failed": "#C0392B",  # red — elaboration error
    "unrealized": "#C05A9E",  # magenta — formalized but no bound decl (over-claim)
    "formalized": "#2E79B5",  # blue — blueprint statement axis (Lean stated)
    "proved": "#1F8A65",  # green — blueprint proof axis (sorry-free, confirmed)
    "axis": "#999999",
    "grid": "#E4E4E422",
    "text": "#333333",
    "text_muted": "#777777",
}

INT_FIELDS = (
    "grey white red yellow light_green dark_green purple exec_total "
    "dot_red dot_yellow dot_green art_total tracked verified verified_trusted "
    "translated "
    # probe-leanblueprint two-axis metrics (blank -> 0 for colour pipelines)
    "bp_nodes_total bp_nodes_bound bp_nodes_planned bp_nodes_decl_missing "
    "bp_def_total bp_def_formalized "
    "bp_thm_total bp_thm_formalized bp_thm_proved bp_thm_proved_confirmed "
    # probe-lean proof-status partition over the formalized nodes (--combined mode)
    "bp_def_verified bp_def_trusted bp_def_in_progress bp_def_failed bp_def_unrealized "
    "bp_thm_verified bp_thm_trusted bp_thm_in_progress bp_thm_failed bp_thm_unrealized"
).split()

# Fields the combined (--combined) chart needs. If a plotted row lacks these
# (an old history predating the columns), we refuse rather than silently render
# them as zero via the coercion in load_records.
COMBINED_FIELDS = [
    f"bp_{k}_{b}"
    for k in ("def", "thm")
    for b in ("total", "formalized", "verified", "trusted", "in_progress", "failed", "unrealized")
]


def _read_rows(path: Path) -> list[dict]:
    """Read raw records (no int coercion), preserving which keys are present."""
    if path.suffix == ".csv":
        with path.open(newline="") as f:
            return list(csvmod.DictReader(f))
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _coerce_ints(rows: list[dict]) -> list[dict]:
    for r in rows:
        for k in INT_FIELDS:
            v = r.get(k, "")
            r[k] = int(v) if str(v).strip() not in ("", "None") else 0
    return rows


def load_records(path: Path) -> list[dict]:
    """Load records from JSONL or CSV, coercing metric fields to int."""
    return _coerce_ints(_read_rows(path))


def _present(row: dict, key: str) -> bool:
    """True if ``key`` was actually populated in the raw row (not absent/blank)."""
    return key in row and str(row.get(key)).strip() not in ("", "None")


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def nice_ceiling(v: int) -> int:
    """Round up to a friendly y-axis maximum."""
    if v <= 0:
        return 10
    for step in (10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if v <= step * 5:
            return int(math.ceil(v / step) * step)
    return int(math.ceil(v / 1000) * 1000)


class Plot:
    """Minimal SVG line/area plotter with a shared coordinate system."""

    def __init__(self, categories, y_max, title, subtitle, y_label, interactive=False):
        self.cats = categories
        self.y_max = y_max
        self.title = title
        self.subtitle = subtitle
        self.y_label = y_label
        # When True, series get `class="series" data-series=KEY` (and legend items
        # `class="legend" ...`) so an HTML wrapper can toggle them in JS. Off by
        # default, so the committed static SVGs are byte-identical.
        self.interactive = interactive
        self.W, self.H = 980, 460
        self.ml, self.mr, self.mt, self.mb = 64, 210, 64, 96
        self.parts: list[str] = []

    def _tag(self, key, *, legend=False, locked=False) -> str:
        """Attributes tying an element to a togglable series (interactive only)."""
        if not self.interactive or key is None:
            return ""
        cls = "legend" if legend else "series"
        attr = f' class="{cls}" data-series="{key}"'
        if legend and locked:
            attr += ' data-locked="1"'
        return attr

    @property
    def plot_w(self):
        return self.W - self.ml - self.mr

    @property
    def plot_h(self):
        return self.H - self.mt - self.mb

    def x(self, i):
        n = len(self.cats)
        if n == 1:
            return self.ml + self.plot_w / 2
        return self.ml + self.plot_w * i / (n - 1)

    def y(self, v):
        return self.mt + self.plot_h * (1 - v / self.y_max)

    def axes(self):
        p = self.parts
        p.append(
            f'<text x="{self.ml}" y="28" font-size="17" font-weight="600" '
            f'fill="{COL["text"]}">{esc(self.title)}</text>'
        )
        if self.subtitle:
            p.append(
                f'<text x="{self.ml}" y="47" font-size="11" '
                f'fill="{COL["text_muted"]}">{esc(self.subtitle)}</text>'
            )
        # y gridlines + ticks (5 divisions)
        for k in range(6):
            val = self.y_max * k / 5
            yy = self.y(val)
            p.append(
                f'<line x1="{self.ml}" y1="{yy:.1f}" x2="{self.ml + self.plot_w}" '
                f'y2="{yy:.1f}" stroke="{COL["grid"]}" />'
            )
            p.append(
                f'<text x="{self.ml - 8}" y="{yy + 4:.1f}" font-size="10" '
                f'text-anchor="end" fill="{COL["text_muted"]}">{int(round(val))}</text>'
            )
        # axes
        p.append(
            f'<line x1="{self.ml}" y1="{self.mt}" x2="{self.ml}" '
            f'y2="{self.mt + self.plot_h}" stroke="{COL["axis"]}" />'
        )
        p.append(
            f'<line x1="{self.ml}" y1="{self.mt + self.plot_h}" '
            f'x2="{self.ml + self.plot_w}" y2="{self.mt + self.plot_h}" '
            f'stroke="{COL["axis"]}" />'
        )
        # y-axis label
        yc = self.mt + self.plot_h / 2
        p.append(
            f'<text x="16" y="{yc:.1f}" font-size="11" fill="{COL["text_muted"]}" '
            f'text-anchor="middle" transform="rotate(-90 16 {yc:.1f})">{esc(self.y_label)}</text>'
        )
        # x labels (rotated)
        for i, c in enumerate(self.cats):
            xx = self.x(i)
            yy = self.mt + self.plot_h + 12
            p.append(
                f'<text x="{xx:.1f}" y="{yy:.1f}" font-size="10" '
                f'fill="{COL["text_muted"]}" text-anchor="end" '
                f'transform="rotate(-40 {xx:.1f} {yy:.1f})">{esc(c)}</text>'
            )

    def area(self, values, color, opacity=0.12, key=None):
        pts = " ".join(f"{self.x(i):.1f},{self.y(v):.1f}" for i, v in enumerate(values))
        base = f"{self.x(len(values) - 1):.1f},{self.y(0):.1f} {self.x(0):.1f},{self.y(0):.1f}"
        self.parts.append(
            f'<polygon{self._tag(key)} points="{pts} {base}" fill="{color}" '
            f'fill-opacity="{opacity}" stroke="none" />'
        )

    def line(self, values, color, width=2.0, dots=True, key=None):
        tag = self._tag(key)
        pts = " ".join(f"{self.x(i):.1f},{self.y(v):.1f}" for i, v in enumerate(values))
        self.parts.append(
            f'<polyline{tag} points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linejoin="round" />'
        )
        if dots:
            for i, v in enumerate(values):
                self.parts.append(
                    f'<circle{tag} cx="{self.x(i):.1f}" cy="{self.y(v):.1f}" '
                    f'r="2.6" fill="{color}" />'
                )

    def legend(self, entries):
        """Entries are ``(label, color)`` or ``(label, color, key[, locked])``; the
        key/locked fields drive interactive toggling and are ignored otherwise."""
        lx = self.ml + self.plot_w + 16
        ly = self.mt + 4
        for i, entry in enumerate(entries):
            label, color = entry[0], entry[1]
            key = entry[2] if len(entry) > 2 else None
            locked = entry[3] if len(entry) > 3 else False
            tag = self._tag(key, legend=True, locked=locked)
            yy = ly + i * 20
            self.parts.append(
                f'<rect{tag} x="{lx}" y="{yy - 9}" width="12" height="12" rx="2" fill="{color}" />'
            )
            self.parts.append(
                f'<text{tag} x="{lx + 18}" y="{yy + 1}" font-size="11" '
                f'fill="{COL["text"]}">{esc(label)}</text>'
            )

    def svg(self) -> str:
        body = "\n  ".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.W}" '
            f'height="{self.H}" viewBox="0 0 {self.W} {self.H}" '
            f'font-family="system-ui, -apple-system, Segoe UI, sans-serif">\n'
            f'  <rect width="{self.W}" height="{self.H}" fill="#FFFFFF" />\n'
            f"  {body}\n</svg>\n"
        )

    def nested_svg(self, x: float = 0, y: float = 0) -> str:
        """This panel as a nested ``<svg>`` at (x, y), for stacking panels in one
        image. Its self-contained 0..W/0..H coordinate box is independent, so a
        parent ``<svg>`` just positions it; the transparent background lets the
        parent's fill show through."""
        body = "\n  ".join(self.parts)
        return (
            f'<svg x="{x}" y="{y}" width="{self.W}" height="{self.H}" '
            f'viewBox="0 0 {self.W} {self.H}">\n  {body}\n</svg>'
        )


def _compose_panels(panels: list[Plot]) -> str:
    """Stack panels vertically into one self-contained SVG."""
    w = panels[0].W
    h = sum(p.H for p in panels)
    nested, oy = [], 0.0
    for p in panels:
        nested.append(p.nested_svg(0, oy))
        oy += p.H
    body = "\n  ".join(nested)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'font-family="system-ui, -apple-system, Segoe UI, sans-serif">\n'
        f'  <rect width="{w}" height="{h}" fill="#FFFFFF" />\n'
        f"  {body}\n</svg>\n"
    )


def burnup_svg(
    ok, title, subtitle, show_in_progress=False, show_unspecified=False, interactive=False
) -> str:
    cats = [r["sample_date"] for r in ok]
    tracked = [r["tracked"] for r in ok]
    vt = [r["verified_trusted"] for r in ok]
    verified = [r["verified"] for r in ok]
    translated = [r["translated"] for r in ok]
    has_translated = any(translated)

    y_max = nice_ceiling(max(tracked) if tracked else 0)
    plot = Plot(cats, y_max, title, subtitle, "atom count", interactive=interactive)
    plot.axes()
    # Largest area first so nested bands read correctly.
    plot.area(tracked, COL["tracked"], 0.08, key="tracked")
    plot.area(vt, COL["verified_trusted"], 0.12, key="verified_trusted")
    plot.area(verified, COL["verified"], 0.16, key="verified")
    plot.line(tracked, COL["tracked"], key="tracked")
    plot.line(vt, COL["verified_trusted"], key="verified_trusted")
    plot.line(verified, COL["verified"], key="verified")
    # `tracked` and `verified` are the baseline: locked on in interactive mode.
    legend = [
        ("tracked (ceiling)", COL["tracked"], "tracked", True),
        ("verified + trusted", COL["verified_trusted"], "verified_trusted"),
        ("verified", COL["verified"], "verified", True),
    ]
    if has_translated:
        plot.line(translated, COL["translated"], key="translated")
        legend.insert(2, ("translated (Aeneas)", COL["translated"], "translated"))
    # Optional status curves, drawn from zero. These are the doc's atom-status
    # counts (colours.py), NOT the frontier gap: the "in-progress" atom status
    # is specifically `yellow` (an incomplete proof — sorry / assume), and it is
    # distinct from `white` (tracked but no spec written yet). The gap between
    # the completion frontier and the ceiling is white + yellow + red, which
    # would conflate the two — so we plot each status on its own line.
    if show_in_progress:
        yellow = [r["yellow"] for r in ok]
        plot.line(yellow, COL["in_progress"], key="in_progress")
        legend.append(("in-progress (sorry/assume)", COL["in_progress"], "in_progress"))
    if show_unspecified:
        white = [r["white"] for r in ok]
        plot.line(white, COL["unspecified"], key="unspecified")
        legend.append(("unspecified (no spec)", COL["unspecified"], "unspecified"))
    # `red` (a failed verification) is auto-drawn when present, like `translated`:
    # it is a rare but critical status that should never sit hidden in the gap, so
    # it needs no opt-in flag, and stays absent (no clutter) when nothing failed.
    red = [r["red"] for r in ok]
    if any(red):
        plot.line(red, COL["failed"], key="failed")
        legend.append(("failed", COL["failed"], "failed"))
    plot.legend(legend)
    return plot.svg()


def blueprint_svg(ok, base_title, subtitle) -> str:
    """Two stacked panels for a leanblueprint history: Definitions (total +
    formalized) and Theorems (total + formalized + proved), mirroring the
    published site. "Proved" is the probe-lean-confirmed count (bp_thm_proved_confirmed).
    A shared y-ceiling keeps the two panels visually comparable."""
    cats = [r["sample_date"] for r in ok]
    def_total = [r["bp_def_total"] for r in ok]
    def_formalized = [r["bp_def_formalized"] for r in ok]
    thm_total = [r["bp_thm_total"] for r in ok]
    thm_formalized = [r["bp_thm_formalized"] for r in ok]
    thm_proved = [r["bp_thm_proved_confirmed"] for r in ok]

    y_max = nice_ceiling(
        max((max(def_total) if def_total else 0), (max(thm_total) if thm_total else 0))
    )

    defs = Plot(cats, y_max, f"{base_title} — definitions", subtitle, "blueprint nodes")
    defs.axes()
    defs.area(def_total, COL["tracked"], 0.08)
    defs.area(def_formalized, COL["formalized"], 0.14)
    defs.line(def_total, COL["tracked"])
    defs.line(def_formalized, COL["formalized"])
    defs.legend([("total (planned)", COL["tracked"]), ("formalized", COL["formalized"])])

    thms = Plot(cats, y_max, f"{base_title} — theorems", "", "blueprint nodes")
    thms.axes()
    thms.area(thm_total, COL["tracked"], 0.08)
    thms.area(thm_formalized, COL["formalized"], 0.14)
    thms.area(thm_proved, COL["proved"], 0.18)
    thms.line(thm_total, COL["tracked"])
    thms.line(thm_formalized, COL["formalized"])
    thms.line(thm_proved, COL["proved"])
    thms.legend(
        [
            ("total (planned)", COL["tracked"]),
            ("formalized", COL["formalized"]),
            ("proved", COL["proved"]),
        ]
    )
    return _compose_panels([defs, thms])


def combined_svg(ok, base_title, subtitle, show_unspecified=False, interactive=False):
    """One panel putting definitions and theorems on a single FC-style chart,
    counting every blueprint node (the y-axis unit).

    Frontiers (nested): ``tracked >= verified+trusted >= verified``. Status curves
    (zero-based): ``in-progress`` (probe-lean ``unverified``: a sorry), ``failed``
    (probe-lean elaboration error) and ``unrealized`` (formalized statement but no
    bound atom with a machine status -- an over-claim / shadow) are drawn only when
    present, so a clean history stays uncluttered; ``unspecified`` (no Lean
    statement) is opt-in via ``show_unspecified``. The completion frontier is the
    probe-lean status of each node's bound atoms (``verified`` = green = verified +
    transitively-verified; ``+trusted`` = axiom/external); the ceiling and the
    unspecified split come from the blueprint statement axis. Returns
    ``(svg, warnings)``; warnings flag any sample where the nesting is violated
    (rendered honestly, not clamped)."""
    cats = [r["sample_date"] for r in ok]
    tracked = [r["bp_def_total"] + r["bp_thm_total"] for r in ok]
    verified = [r["bp_def_verified"] + r["bp_thm_verified"] for r in ok]
    verified_trusted = [
        v + r["bp_def_trusted"] + r["bp_thm_trusted"] for v, r in zip(verified, ok, strict=True)
    ]
    in_progress = [r["bp_def_in_progress"] + r["bp_thm_in_progress"] for r in ok]
    failed = [r["bp_def_failed"] + r["bp_thm_failed"] for r in ok]
    unrealized = [r["bp_def_unrealized"] + r["bp_thm_unrealized"] for r in ok]
    unspecified = [
        (r["bp_def_total"] - r["bp_def_formalized"]) + (r["bp_thm_total"] - r["bp_thm_formalized"])
        for r in ok
    ]

    warnings: list[str] = []
    for i, d in enumerate(cats):
        if not (verified[i] <= verified_trusted[i] <= tracked[i]):
            warnings.append(
                f"{d}: frontier nesting violated "
                f"(verified {verified[i]} <= verified+trusted {verified_trusted[i]} "
                f"<= tracked {tracked[i]})"
            )
        for name, series in (("in-progress", in_progress), ("failed", failed)):
            if series[i] > tracked[i]:
                warnings.append(f"{d}: {name} ({series[i]}) exceeds tracked ({tracked[i]})")

    y_max = nice_ceiling(max(tracked) if tracked else 0)
    plot = Plot(cats, y_max, f"{base_title} — combined", subtitle, "blueprint nodes", interactive)
    plot.axes()
    # Nested frontiers, largest area first.
    plot.area(tracked, COL["tracked"], 0.08, key="tracked")
    plot.area(verified_trusted, COL["verified_trusted"], 0.12, key="verified_trusted")
    plot.area(verified, COL["verified"], 0.16, key="verified")
    plot.line(tracked, COL["tracked"], key="tracked")
    plot.line(verified_trusted, COL["verified_trusted"], key="verified_trusted")
    plot.line(verified, COL["verified"], key="verified")
    # Band names match the FC colour burn-up (burnup_svg) so the two charts read
    # with one vocabulary; the node-vs-atom unit and blueprint-vs-probe-lean
    # provenance live in the subtitle and the "How to read" docs. `tracked` and
    # `verified` are the baseline: locked on in interactive mode.
    legend = [
        ("tracked (ceiling)", COL["tracked"], "tracked", True),
        ("verified + trusted", COL["verified_trusted"], "verified_trusted"),
        ("verified", COL["verified"], "verified", True),
    ]
    # Zero-based status curves, drawn only when present (like `translated` /
    # `failed` on the colour burn-up) so a clean history stays uncluttered.
    if any(in_progress):
        plot.line(in_progress, COL["in_progress"], key="in_progress")
        legend.append(("in-progress (sorry/assume)", COL["in_progress"], "in_progress"))
    if any(failed):
        plot.line(failed, COL["failed"], key="failed")
        legend.append(("failed", COL["failed"], "failed"))
    if any(unrealized):
        plot.line(unrealized, COL["unrealized"], key="unrealized")
        legend.append(("unrealized (no bound status)", COL["unrealized"], "unrealized"))
    if show_unspecified:
        plot.line(unspecified, COL["unspecified"], key="unspecified")
        legend.append(("unspecified (no statement)", COL["unspecified"], "unspecified"))
    plot.legend(legend)
    # Stamp nesting warnings into the image rather than clamping the bands.
    for j, w in enumerate(warnings[:3]):
        yy = plot.H - 30 + j * 12
        plot.parts.append(
            f'<text x="{plot.ml}" y="{yy}" font-size="10" fill="{COL["failed"]}">⚠ {esc(w)}</text>'
        )
    return plot.svg(), warnings


# Standalone interactive HTML: inline the (series-tagged) SVG and toggle series on
# a legend click, with `tracked`/`verified` locked on. Vanilla JS, no libraries.
# NOTE: proof-of-concept for adapting into VeriLib — GitHub strips scripts from
# rendered SVG, so the toggles only work when the .html is opened in a browser.
# A plain template (not an f-string) so the JS/CSS braces stay unescaped.
_INTERACTIVE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__TITLE__</title>
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 1.5rem; color: #333; }
  p.hint { color: #777; font-size: 13px; margin: 0 0 .75rem; }
  .series.off { display: none; }
  .legend { cursor: pointer; }
  .legend[data-locked] { cursor: default; }
  .legend.dim { opacity: .3; }
</style>
</head>
<body>
<p class="hint">Click a legend entry to show or hide that series.
<strong>tracked</strong> and <strong>verified</strong> are locked on.</p>
__SVG__
<script>
(function () {
  function bySeries(cls, key) {
    return document.querySelectorAll('.' + cls + '[data-series="' + key + '"]');
  }
  document.querySelectorAll('.legend[data-series]').forEach(function (el) {
    el.addEventListener('click', function () {
      if (el.hasAttribute('data-locked')) return;
      var key = el.getAttribute('data-series');
      var series = bySeries('series', key);
      if (!series.length) return;
      var hide = !series[0].classList.contains('off');
      series.forEach(function (s) { s.classList.toggle('off', hide); });
      bySeries('legend', key).forEach(function (l) { l.classList.toggle('dim', hide); });
    });
  });
})();
</script>
</body>
</html>
"""


def interactive_html(svg: str, title: str) -> str:
    """Wrap a series-tagged SVG (``interactive=True``) in a standalone HTML page
    with a click-to-toggle legend. See ``_INTERACTIVE_HTML``."""
    return _INTERACTIVE_HTML.replace("__TITLE__", esc(title)).replace("__SVG__", svg)


# SVG->PNG converters tried in order (first on PATH wins). The SVG is always the
# primary output; PNG is an opt-in convenience, so we shell out rather than take
# a Python dependency, and degrade gracefully when none is installed.
PNG_CONVERTERS = (
    ("rsvg-convert", lambda svg, png, s: ["rsvg-convert", "-z", str(s), "-o", str(png), str(svg)]),
    (
        "inkscape",
        lambda svg, png, s: [
            "inkscape",
            str(svg),
            "--export-type=png",
            f"--export-filename={png}",
            "--export-dpi",
            str(int(96 * s)),
        ],
    ),
    (
        "convert",
        lambda svg, png, s: [
            "convert",
            "-density",
            str(int(96 * s)),
            "-background",
            "none",
            str(svg),
            str(png),
        ],
    ),
)


def svg_to_png(svg_path: Path, png_path: Path, scale: float) -> bool:
    """Rasterize an SVG to PNG via the first available converter. Returns
    True on success; prints a hint and returns False if none is on PATH."""
    for name, build_cmd in PNG_CONVERTERS:
        if shutil.which(name) is None:
            continue
        cmd = build_cmd(svg_path, png_path, scale)
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"{name} failed: {e.stderr.decode(errors='replace').strip()}", file=sys.stderr)
            return False
        print(f"wrote {png_path} (via {name})")
        return True
    print(
        "no SVG->PNG converter found (install rsvg-convert, inkscape, or "
        "imagemagick); wrote SVG only",
        file=sys.stderr,
    )
    return False


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Render a verification burn-up SVG from a progress history file."
    )
    p.add_argument("input", type=Path, help="progress-<name>.jsonl or .csv")
    p.add_argument("-o", "--output", type=Path, help="Output SVG (default: alongside input).")
    p.add_argument("--title", help="Chart title (default: derived from the repo).")
    p.add_argument(
        "--in-progress",
        action="store_true",
        help="Also draw the in-progress curve: the `yellow` atom count "
        "(incomplete proof — sorry / assume), per the VeriLib status model.",
    )
    p.add_argument(
        "--unspecified",
        action="store_true",
        help="Also draw the unspecified curve: the `white` atom count "
        "(tracked but no spec written yet). Distinct from --in-progress.",
    )
    p.add_argument(
        "--combined",
        action="store_true",
        help="leanblueprint only: render a single-panel chart pooling definitions "
        "and theorems (counted as blueprint nodes), FC-aligned: tracked / "
        "verified+trusted / verified, plus in-progress / failed / unrealized. "
        "Writes burnup-combined.svg; --unspecified adds the no-statement curve.",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="With --combined, exit non-zero if any sample violates the frontier "
        "nesting (the warning is stamped into the SVG either way).",
    )
    p.add_argument(
        "--interactive",
        action="store_true",
        help="Also write a standalone .html next to the SVG whose legend toggles "
        "series on click (tracked/verified locked on). Vanilla JS, no deps; a "
        "proof-of-concept for VeriLib. Not supported for the two-panel blueprint "
        "chart. Note: GitHub strips SVG scripts, so open the .html in a browser.",
    )
    p.add_argument(
        "--png",
        action="store_true",
        help="Also write a PNG alongside the SVG (needs rsvg-convert, "
        "inkscape, or imagemagick on PATH).",
    )
    p.add_argument(
        "--png-scale",
        type=float,
        default=2.0,
        help="PNG raster scale factor (default: 2.0 for crisp output).",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    records = load_records(args.input)
    ok = [r for r in records if r.get("status") == "ok"]
    if not ok:
        print("no ok samples to plot", file=sys.stderr)
        return 1

    repo = ok[0].get("repo", args.input.stem)
    n_gap = len(records) - len(ok)
    subtitle = (
        f"{repo} · {len(ok)} samples"
        + (f" · {n_gap} gap(s) omitted" if n_gap else "")
        + f" · source: {args.input.name}"
    )

    pipeline = ok[0].get("pipeline")
    if args.combined and pipeline != "leanblueprint":
        print(
            f"[error] --combined is a leanblueprint-only chart; pipeline is {pipeline!r}.",
            file=sys.stderr,
        )
        return 2

    combined_warnings: list[str] = []
    interactive_svg: str | None = None  # tagged SVG for the --interactive .html
    if pipeline == "leanblueprint" and args.combined:
        # Refuse to plot silent-zero curves on a history predating the columns:
        # check the raw rows (pre-coercion), so absent != 0.
        raw_ok = [r for r in _read_rows(args.input) if r.get("status") == "ok"]
        missing = sorted(
            r.get("sample_date", "?")
            for r in raw_ok
            if not all(_present(r, f) for f in COMBINED_FIELDS)
        )
        if missing:
            print(
                "[error] --combined needs the per-node proof-status columns "
                f"(bp_def_verified, bp_thm_verified, ...), absent for samples: "
                f"{', '.join(missing)}. Re-extract this history to populate them.",
                file=sys.stderr,
            )
            return 2
        if args.in_progress:
            print(
                "[note] in-progress is drawn when present in --combined; --in-progress ignored.",
                file=sys.stderr,
            )
        # Names match the FC chart; the differing unit/provenance goes here so it
        # is always on the chart (see "How to read the charts" in the README).
        combined_subtitle = subtitle + " · unit: blueprint node · proof status: probe-lean"
        svg, combined_warnings = combined_svg(
            ok, args.title or repo, combined_subtitle, show_unspecified=args.unspecified
        )
        if args.interactive:
            interactive_svg = combined_svg(
                ok, args.title or repo, combined_subtitle, args.unspecified, interactive=True
            )[0]
    elif pipeline == "leanblueprint":
        if args.in_progress or args.unspecified:
            print(
                "[note] --in-progress/--unspecified are colour-pipeline options; "
                "ignored for leanblueprint (use --combined for the combined chart).",
                file=sys.stderr,
            )
        if args.interactive:
            print(
                "[note] --interactive is not supported for the two-panel blueprint "
                "chart; use --combined for an interactive combined chart.",
                file=sys.stderr,
            )
        svg = blueprint_svg(ok, args.title or repo, subtitle)
    else:
        title = args.title or f"{repo} — verification burn-up"
        svg = burnup_svg(
            ok,
            title,
            subtitle,
            show_in_progress=args.in_progress,
            show_unspecified=args.unspecified,
        )
        if args.interactive:
            interactive_svg = burnup_svg(
                ok, title, subtitle, args.in_progress, args.unspecified, interactive=True
            )
    # Default alongside the input: data/<name>/progress.jsonl -> .../burnup.svg.
    # --combined writes a distinct stem so it never overwrites the two-panel chart.
    kind = "burnup-combined" if args.combined else "burnup"
    default_stem = kind if args.input.stem == "progress" else f"{args.input.stem}-{kind}"
    out = args.output or args.input.with_name(f"{default_stem}.svg")
    out.write_text(svg)
    print(f"wrote {out}")
    if args.png:
        svg_to_png(out, out.with_suffix(".png"), args.png_scale)
    if interactive_svg is not None:
        html_out = out.with_suffix(".html")
        html_out.write_text(interactive_html(interactive_svg, args.title or repo))
        print(f"wrote {html_out}")
    for w in combined_warnings:
        print(f"[warn] {w}", file=sys.stderr)
    if combined_warnings and args.strict:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

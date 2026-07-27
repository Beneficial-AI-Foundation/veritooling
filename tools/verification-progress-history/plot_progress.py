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
    "axis": "#999999",
    "grid": "#E4E4E422",
    "text": "#333333",
    "text_muted": "#777777",
}

INT_FIELDS = (
    "grey white red yellow light_green dark_green purple exec_total "
    "dot_red dot_yellow dot_green art_total tracked verified verified_trusted "
    "translated"
).split()


def load_records(path: Path) -> list[dict]:
    """Load records from JSONL or CSV, coercing metric fields to int."""
    if path.suffix == ".csv":
        with path.open(newline="") as f:
            rows = list(csvmod.DictReader(f))
    else:
        rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    for r in rows:
        for k in INT_FIELDS:
            v = r.get(k, "")
            r[k] = int(v) if str(v).strip() not in ("", "None") else 0
    return rows


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

    def __init__(self, categories, y_max, title, subtitle, y_label):
        self.cats = categories
        self.y_max = y_max
        self.title = title
        self.subtitle = subtitle
        self.y_label = y_label
        self.W, self.H = 980, 460
        self.ml, self.mr, self.mt, self.mb = 64, 210, 64, 96
        self.parts: list[str] = []

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

    def area(self, values, color, opacity=0.12):
        pts = " ".join(f"{self.x(i):.1f},{self.y(v):.1f}" for i, v in enumerate(values))
        base = f"{self.x(len(values) - 1):.1f},{self.y(0):.1f} {self.x(0):.1f},{self.y(0):.1f}"
        self.parts.append(
            f'<polygon points="{pts} {base}" fill="{color}" '
            f'fill-opacity="{opacity}" stroke="none" />'
        )

    def line(self, values, color, width=2.0, dots=True):
        pts = " ".join(f"{self.x(i):.1f},{self.y(v):.1f}" for i, v in enumerate(values))
        self.parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linejoin="round" />'
        )
        if dots:
            for i, v in enumerate(values):
                self.parts.append(
                    f'<circle cx="{self.x(i):.1f}" cy="{self.y(v):.1f}" r="2.6" fill="{color}" />'
                )

    def legend(self, entries):
        lx = self.ml + self.plot_w + 16
        ly = self.mt + 4
        for i, (label, color) in enumerate(entries):
            yy = ly + i * 20
            self.parts.append(
                f'<rect x="{lx}" y="{yy - 9}" width="12" height="12" rx="2" fill="{color}" />'
            )
            self.parts.append(
                f'<text x="{lx + 18}" y="{yy + 1}" font-size="11" '
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


def burnup_svg(ok, title, subtitle, show_in_progress=False, show_unspecified=False) -> str:
    cats = [r["sample_date"] for r in ok]
    tracked = [r["tracked"] for r in ok]
    vt = [r["verified_trusted"] for r in ok]
    verified = [r["verified"] for r in ok]
    translated = [r["translated"] for r in ok]
    has_translated = any(translated)

    y_max = nice_ceiling(max(tracked) if tracked else 0)
    plot = Plot(cats, y_max, title, subtitle, "atom count")
    plot.axes()
    # Largest area first so nested bands read correctly.
    plot.area(tracked, COL["tracked"], 0.08)
    plot.area(vt, COL["verified_trusted"], 0.12)
    plot.area(verified, COL["verified"], 0.16)
    plot.line(tracked, COL["tracked"])
    plot.line(vt, COL["verified_trusted"])
    plot.line(verified, COL["verified"])
    legend = [
        ("tracked (ceiling)", COL["tracked"]),
        ("verified + trusted", COL["verified_trusted"]),
        ("verified", COL["verified"]),
    ]
    if has_translated:
        plot.line(translated, COL["translated"])
        legend.insert(2, ("translated (Aeneas)", COL["translated"]))
    # Optional status curves, drawn from zero. These are the doc's atom-status
    # counts (colours.py), NOT the frontier gap: the "in-progress" atom status
    # is specifically `yellow` (an incomplete proof — sorry / assume), and it is
    # distinct from `white` (tracked but no spec written yet). The gap between
    # the completion frontier and the ceiling is white + yellow + red, which
    # would conflate the two — so we plot each status on its own line.
    if show_in_progress:
        yellow = [r["yellow"] for r in ok]
        plot.line(yellow, COL["in_progress"])
        legend.append(("in-progress (sorry/assume)", COL["in_progress"]))
    if show_unspecified:
        white = [r["white"] for r in ok]
        plot.line(white, COL["unspecified"])
        legend.append(("unspecified (no spec)", COL["unspecified"]))
    plot.legend(legend)
    return plot.svg()


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

    title = args.title or f"{repo} — verification burn-up"
    svg = burnup_svg(
        ok, title, subtitle, show_in_progress=args.in_progress, show_unspecified=args.unspecified
    )
    # Default alongside the input: data/<name>/progress.jsonl -> .../burnup.svg.
    # (Pass -o for variants like burnup-inprogress.svg so they don't collide.)
    default_stem = "burnup" if args.input.stem == "progress" else f"{args.input.stem}-burnup"
    out = args.output or args.input.with_name(f"{default_stem}.svg")
    out.write_text(svg)
    print(f"wrote {out}")
    if args.png:
        svg_to_png(out, out.with_suffix(".png"), args.png_scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

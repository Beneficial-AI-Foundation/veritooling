#!/usr/bin/env python3
"""Render a verification progress burn-up chart from a progress history file.

Reads the JSONL (or CSV) produced by ``progress_history.py`` and writes a
self-contained **SVG** — no third-party dependencies, Python 3 stdlib only, so
the chart is reproducible in-repo and reviewable as text.

Every chart draws the **three categories** defined in the VeriLib "Verification
progress metrics" doc, section "The three categories":

    tracked      in verification scope — the ceiling
    in-progress  `unverified`: a spec exists, the proof is incomplete (sorry/assume)
    completed    `verified` + `transitively-verified` + `trusted`

`tracked` is the ceiling (``tracked ≥ completed`` and ``tracked ≥ in-progress``),
and `in-progress` / `completed` are disjoint but do **not** sum to `tracked` — the
remaining gap holds the units that are neither, `unspecified` (white) and `failed`
(red). Everything beyond those three is opt-in; most flags add one bucket of the
summary partition (drawn from zero). `--translated` is a milestone overlay, so the
default chart says one thing per pipeline:
    --trusted      purple: the axiom-backed part of `completed`
    --unspecified  white: in scope, no spec written yet (no statement, for blueprints)
    --failed       red: a failed verification / elaboration error
    --translated   the Aeneas-only translated milestone
    --unrealized   leanblueprint: formalized but no bound declaration (an over-claim)

Only the unit differs per pipeline: a Rust ``exec`` atom for Verus/Aeneas, a Lean
declaration for ``lean``, a blueprint node for ``leanblueprint``. Lean projects get
one panel with definitions and theorems pooled; ``--split`` restores the older
two-panel Definitions/Theorems layout, which keeps its own richer per-pipeline
vocabulary (blueprint ``formalized``/``proved``, lean ``without sorry``/``trust
boundary``).

The mode is auto-detected from the records.

Only ``status == ok`` samples are plotted; gaps (verify_error, timeout, …) are
skipped, matching how the chart is defined.

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
from dataclasses import dataclass, field
from pathlib import Path

# Scheme colours (hex from the engineering-docs palette; see "Atom statuses and
# colours"). Kept literal so the SVG is dependency-free and self-describing.
COL = {
    "tracked": "#888899",  # neutral ceiling
    "completed": "#1F8A65",  # green — verified + transitively-verified + trusted
    "trusted": "#7B64B8",  # purple — the axiom-backed part of `completed`
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

# The three categories every default chart draws. Spelled out in full so the
# chart is self-describing without the docs to hand.
LBL_TRACKED = "tracked (ceiling)"
LBL_IN_PROGRESS = "in-progress (sorry/assume)"
LBL_COMPLETED = "completed (verified + transitively-verified + trusted)"

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
    "bp_thm_verified bp_thm_trusted bp_thm_in_progress bp_thm_failed bp_thm_unrealized "
    # probe-lean kind-split metrics (the `lean` pipeline; blank otherwise)
    "lean_def_total lean_def_sorry lean_def_verified lean_def_trans_verified "
    "lean_def_trusted lean_def_failed "
    "lean_thm_total lean_thm_sorry lean_thm_verified lean_thm_trans_verified "
    "lean_thm_trusted lean_thm_failed"
).split()

# Fields the pooled leanblueprint chart needs. If a plotted row lacks these (an
# old history predating the columns), we refuse rather than silently render them
# as zero via the coercion in load_records.
BP_POOLED_FIELDS = [
    f"bp_{k}_{b}"
    for k in ("def", "thm")
    for b in ("total", "formalized", "verified", "trusted", "in_progress", "failed", "unrealized")
]

# The lean-pipeline analogue: the kind-split tallies the pooled lean chart sums.
LEAN_POOLED_FIELDS = [
    f"lean_{k}_{b}"
    for k in ("def", "thm")
    for b in ("total", "sorry", "verified", "trans_verified", "trusted", "failed")
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
        # Grow the canvas rightward if the widest label would overflow, so long
        # frontier names (e.g. "verified + transitively-verified + trusted") are
        # not clipped. The plot area is already drawn against the original width,
        # so this only extends the right margin; charts with short legends keep
        # the default width and their SVGs are unchanged.
        widest = max((len(label) for label, _ in entries), default=0)
        needed = lx + 18 + int(widest * 6.3) + 12
        if needed > self.W:
            self.W = needed
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


@dataclass(frozen=True)
class Overlays:
    """Which opt-in curves to add on top of the three default categories.

    Each is one flag on the CLI. They are off by default so every chart makes a
    single statement — the three categories — regardless of pipeline; a non-zero
    series behind a disabled flag is reported on stderr rather than silently
    dropped (see ``_overlay``)."""

    trusted: bool = False
    unspecified: bool = False
    failed: bool = False
    translated: bool = False
    unrealized: bool = False


# The default: three categories, nothing else. Frozen, so sharing one is safe.
NO_OVERLAYS = Overlays()

OVERLAY_FLAGS = ("trusted", "unspecified", "failed", "translated", "unrealized")

# Which overlays each pipeline can actually draw. Asking for one that does not
# apply earns a note rather than a flat zero line posing as data: `translated` is
# an Aeneas field, `unrealized` needs the blueprint statement axis, and plain Lean
# has no statement axis at all, so nothing there is `unspecified`.
APPLICABLE_OVERLAYS = {
    "verus": ("trusted", "unspecified", "failed"),
    "aeneas": ("trusted", "unspecified", "failed", "translated"),
    "leanblueprint": ("trusted", "unspecified", "failed", "unrealized"),
    "lean": ("trusted", "failed"),
}


@dataclass
class Rendered:
    """A finished chart plus anything the caller should say about it.

    ``warnings`` are invariant violations (``tracked >= completed`` and
    ``tracked >= in-progress``): stamped into the image and escalated by
    ``--strict``. ``notes`` are advisory — a series that exists but is not drawn
    because its flag is off."""

    svg: str
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _overlay(plot, legend, notes, values, key, label, flag, enabled, notable=False):
    """Draw one zero-based opt-in status curve, or note that it was withheld.

    ``notable`` marks the two overlays that report trouble — a failed
    verification, a blueprint over-claim. Both sit in the gap between `completed`
    and `tracked`, so with the curve off a project that started failing would show
    no change at all on the chart; the stderr note is what keeps that visible. The
    ordinary states (`unspecified`, `translated`) are non-zero on nearly every
    project, so noting them every run would be noise."""
    if enabled:
        plot.line(values, COL[key])
        legend.append((label, COL[key]))
    elif notable and any(values):
        notes.append(f"{label.split(' (')[0]} peaks at {max(values)}; pass {flag} to draw it")


def _categories_chart(
    cats,
    series,
    title,
    subtitle,
    unit,
    overlays,
    ceiling_label=LBL_TRACKED,
    ceiling_word="tracked",
    unspecified_label="unspecified (no spec)",
) -> Rendered:
    """Render the three-category chart. The one renderer behind every pipeline.

    ``series`` maps category/status names to per-sample lists: ``tracked``,
    ``in_progress`` and ``completed`` are required; the ``trusted`` /
    ``unspecified`` / ``failed`` / ``translated`` / ``unrealized`` overlays are
    optional and read as zero when absent. Only the y-axis ``unit`` and the
    ceiling's name differ across pipelines: the ceiling is a genuine curated
    ``tracked`` set for Verus/Aeneas and leanblueprint, but plain Lean has no such
    number — there it is just probe-lean's declaration count, so it is labelled
    ``total`` (``ceiling_label``/``ceiling_word``).

    Invariant violations are stamped onto the image rather than clamped, so a
    projection or a probe bug is visible instead of quietly smoothed away."""
    zeros = [0] * len(cats)
    tracked, in_progress, completed = series["tracked"], series["in_progress"], series["completed"]

    warnings: list[str] = []
    for i, d in enumerate(cats):
        for name, value in (("completed", completed[i]), ("in-progress", in_progress[i])):
            if value > tracked[i]:
                warnings.append(f"{d}: {name} ({value}) exceeds {ceiling_word} ({tracked[i]})")

    y_max = nice_ceiling(max(tracked) if tracked else 0)
    plot = Plot(cats, y_max, title, subtitle, unit)
    plot.axes()
    # Nested bands, largest area first: tracked contains completed. in-progress is
    # disjoint from completed and is not part of the nesting, so it is a bare line
    # drawn from zero, as every opt-in overlay below is.
    plot.area(tracked, COL["tracked"], 0.08)
    plot.area(completed, COL["completed"], 0.14)
    plot.line(tracked, COL["tracked"])
    plot.line(completed, COL["completed"])
    plot.line(in_progress, COL["in_progress"])
    legend = [
        (ceiling_label, COL["tracked"]),
        (LBL_COMPLETED, COL["completed"]),
        (LBL_IN_PROGRESS, COL["in_progress"]),
    ]
    notes: list[str] = []
    # Every overlay is one bucket of the summary partition, drawn from zero. That
    # includes `trusted`, which is the part of `completed` resting on axioms: the
    # count is easier to read off the axis than a band between two nested lines.
    for key, label, flag, enabled, notable in (
        ("trusted", "trusted (axiom-backed)", "--trusted", overlays.trusted, False),
        ("translated", "translated (Aeneas)", "--translated", overlays.translated, False),
        ("unspecified", unspecified_label, "--unspecified", overlays.unspecified, False),
        ("failed", "failed", "--failed", overlays.failed, True),
        ("unrealized", "unrealized (no bound status)", "--unrealized", overlays.unrealized, True),
    ):
        _overlay(plot, legend, notes, series.get(key, zeros), key, label, flag, enabled, notable)
    plot.legend(legend)
    for j, w in enumerate(warnings[:3]):
        yy = plot.H - 30 + j * 12
        plot.parts.append(
            f'<text x="{plot.ml}" y="{yy}" font-size="10" fill="{COL["failed"]}">⚠ {esc(w)}</text>'
        )
    return Rendered(plot.svg(), warnings, notes)


def burnup_svg(ok, title, subtitle, overlays=NO_OVERLAYS) -> Rendered:
    """Colour-pipeline chart (Verus/Aeneas), unit: a Rust ``exec`` atom.

    Maps the seven bar colours onto the three categories: ``tracked`` is
    ``exec_total`` minus grey, ``completed`` is light + dark green + purple (the
    stored ``verified_trusted``), and ``in-progress`` is ``yellow``. ``white`` and
    ``red`` are the gap, available via ``--unspecified`` / ``--failed``; ``purple``
    is the axiom-backed slice of ``completed``, available via ``--trusted``."""
    return _categories_chart(
        [r["sample_date"] for r in ok],
        {
            "tracked": [r["tracked"] for r in ok],
            "in_progress": [r["yellow"] for r in ok],
            "completed": [r["verified_trusted"] for r in ok],
            "trusted": [r["purple"] for r in ok],
            "unspecified": [r["white"] for r in ok],
            "failed": [r["red"] for r in ok],
            "translated": [r["translated"] for r in ok],
        },
        title,
        subtitle,
        "atom count",
        overlays,
    )


def blueprint_svg(ok, base_title, subtitle) -> Rendered:
    """``--split`` layout for a leanblueprint history: two stacked panels,
    Definitions (total + formalized) and Theorems (total + formalized + proved),
    mirroring the published site. "Proved" is the probe-lean-confirmed count
    (bp_thm_proved_confirmed). A shared y-ceiling keeps the two panels visually
    comparable.

    This is the one chart that does not speak the three-category vocabulary: the
    blueprint's own two axes (does a Lean statement exist, is its proof closed) are
    what the site publishes, and pooling them would collapse the `proved` axis. The
    default chart is ``bp_pooled_svg``."""
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
    return Rendered(_compose_panels([defs, thms]))


def _lean_panel(cats, m, prefix, title, subtitle, y_max):
    """One kind panel (definitions or theorems) with three nested frontiers.

    total >= without-sorry >= trust-boundary. The gap total - without-sorry is
    ``sorry + failed`` (plus any unrecognised/absent status -- count_lean warns on
    those), NOT the sorry count alone; without-sorry - trust-boundary is the
    locally-clean-but-transitively-contaminated set. ``failed`` (an elaboration
    error) is drawn as its own zero-based curve when present, so a failure is not
    silently folded into that gap. Derived from the raw per-status counts so the
    stored record stays faithful to probe-lean's own statuses."""
    total = [r[f"{prefix}total"] for r in m]
    no_sorry = [
        r[f"{prefix}verified"] + r[f"{prefix}trans_verified"] + r[f"{prefix}trusted"] for r in m
    ]
    trust = [r[f"{prefix}trans_verified"] + r[f"{prefix}trusted"] for r in m]
    failed = [r[f"{prefix}failed"] for r in m]

    p = Plot(cats, y_max, title, subtitle, "declarations")
    p.axes()
    # Largest first so the nested bands read correctly.
    p.area(total, COL["tracked"], 0.08)
    p.area(no_sorry, COL["formalized"], 0.14)
    p.area(trust, COL["proved"], 0.18)
    p.line(total, COL["tracked"])
    p.line(no_sorry, COL["formalized"])
    p.line(trust, COL["proved"])
    legend = [
        ("total", COL["tracked"]),
        ("without sorry", COL["formalized"]),
        ("trust boundary", COL["proved"]),
    ]
    # Zero-based; drawn only when some sample failed, so a clean history stays
    # uncluttered and failures never masquerade as sorries. Unlike the default
    # chart's --failed overlay this stays automatic: the split layout is the
    # diagnostic view, so it errs towards showing more.
    if any(failed):
        p.line(failed, COL["failed"])
        legend.append(("failed", COL["failed"]))
    p.legend(legend)
    return p


def lean_svg(ok, base_title, subtitle) -> Rendered:
    """``--split`` layout for a plain-Lean (no-blueprint) history: two stacked
    panels, Definitions and Theorems, each with total / without-sorry /
    trust-boundary. "Without sorry" = verified + transitively-verified + trusted
    (the default chart's ``completed``); "trust boundary" = transitively-verified +
    trusted, which is sound modulo the axioms/external trust base and so a
    different cut from ``--trusted``. Unlike a blueprint history there is no fixed ceiling --
    total is the declaration count, which grows over time. A shared y-ceiling keeps
    the two panels comparable. The default chart is ``lean_pooled_svg``."""
    cats = [r["sample_date"] for r in ok]
    y_max = nice_ceiling(
        max(
            max((r["lean_def_total"] for r in ok), default=0),
            max((r["lean_thm_total"] for r in ok), default=0),
        )
    )
    # Subtitle only on the top panel, matching blueprint_svg.
    defs = _lean_panel(cats, ok, "lean_def_", f"{base_title} — definitions", subtitle, y_max)
    thms = _lean_panel(cats, ok, "lean_thm_", f"{base_title} — theorems", "", y_max)
    return Rendered(_compose_panels([defs, thms]))


def bp_pooled_svg(ok, base_title, subtitle, overlays=NO_OVERLAYS) -> Rendered:
    """Default leanblueprint chart: one panel pooling definitions and theorems,
    counting every blueprint node (the y-axis unit).

    Pooling is safe because the three categories apply uniformly to both kinds — a
    definition is `completed` when its body is sorry-free and checks, a theorem when
    its proof is — so the blueprint's separate `formalized`/`proved` axes are only
    needed for the ``--split`` view (``blueprint_svg``).

    `completed` is the probe-lean status of each node's bound atoms (verified +
    transitively-verified + trusted), not a hand-toggled ``\\leanok``. The ceiling
    and the ``--unspecified`` split come from the blueprint statement axis, so
    `unspecified` here means "no formalized statement yet"."""
    cats = [r["sample_date"] for r in ok]
    trusted = [r["bp_def_trusted"] + r["bp_thm_trusted"] for r in ok]
    return _categories_chart(
        cats,
        {
            "tracked": [r["bp_def_total"] + r["bp_thm_total"] for r in ok],
            "in_progress": [r["bp_def_in_progress"] + r["bp_thm_in_progress"] for r in ok],
            "completed": [
                r["bp_def_verified"] + r["bp_thm_verified"] + t
                for t, r in zip(trusted, ok, strict=True)
            ],
            "trusted": trusted,
            "unspecified": [
                (r["bp_def_total"] - r["bp_def_formalized"])
                + (r["bp_thm_total"] - r["bp_thm_formalized"])
                for r in ok
            ],
            "failed": [r["bp_def_failed"] + r["bp_thm_failed"] for r in ok],
            "unrealized": [r["bp_def_unrealized"] + r["bp_thm_unrealized"] for r in ok],
        },
        base_title,
        subtitle,
        "blueprint nodes",
        overlays,
        unspecified_label="unspecified (no statement)",
    )


def lean_pooled_svg(ok, base_title, subtitle, overlays=NO_OVERLAYS) -> Rendered:
    """Default plain-Lean chart: one panel pooling definitions and theorems,
    counting every Lean declaration (the y-axis unit).

    Maps the kind-split probe-lean tallies onto the three categories, matching
    ``colors.py``: `completed` = verified + transitively-verified + trusted (the
    ``--split`` view's "without sorry"), `in-progress` = ``sorry``
    (``unverified``). Because every declaration is counted, `in-progress` here is
    the project's full sorry count — the blueprint chart has no such guarantee.

    Lean has no blueprint statement axis, so `unspecified` and `unrealized` do not
    apply. The ceiling is just probe-lean's declaration count, which grows with the
    project, so it is labelled ``total``: there is no curated tracked set to draw."""
    verified = [
        r["lean_def_verified"]
        + r["lean_def_trans_verified"]
        + r["lean_thm_verified"]
        + r["lean_thm_trans_verified"]
        for r in ok
    ]
    trusted = [r["lean_def_trusted"] + r["lean_thm_trusted"] for r in ok]
    return _categories_chart(
        [r["sample_date"] for r in ok],
        {
            "tracked": [r["lean_def_total"] + r["lean_thm_total"] for r in ok],
            "in_progress": [r["lean_def_sorry"] + r["lean_thm_sorry"] for r in ok],
            "completed": [v + t for v, t in zip(verified, trusted, strict=True)],
            "trusted": trusted,
            "failed": [r["lean_def_failed"] + r["lean_thm_failed"] for r in ok],
        },
        base_title,
        subtitle,
        "declarations",
        overlays,
        ceiling_label="total (ceiling)",
        ceiling_word="total",
    )


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
        "--trusted",
        action="store_true",
        help="Also draw the trusted curve (`purple`): the axiom-backed part of "
        "`completed`, i.e. how much of the completed set rests on an axiom or an "
        "external declaration rather than a proof.",
    )
    p.add_argument(
        "--unspecified",
        action="store_true",
        help="Also draw the unspecified curve: in scope but with no spec written "
        "yet (`white` for Verus/Aeneas, no formalized statement for leanblueprint). "
        "Not applicable to plain lean.",
    )
    p.add_argument(
        "--failed",
        action="store_true",
        help="Also draw the failed curve (`red`): a failed verification or "
        "elaboration error. Withheld failures are reported on stderr.",
    )
    p.add_argument(
        "--translated",
        action="store_true",
        help="Also draw the Aeneas-only `translated` milestone: non-disabled exec "
        "atoms with a translation-name. Ignored by the other pipelines.",
    )
    p.add_argument(
        "--unrealized",
        action="store_true",
        help="Also draw the leanblueprint-only `unrealized` curve: nodes claiming "
        "a formalized statement with no bound declaration (an over-claim).",
    )
    p.add_argument(
        "--split",
        action="store_true",
        help="leanblueprint / lean: render the older two-panel layout instead, one "
        "panel for definitions and one for theorems, in each pipeline's own richer "
        "vocabulary (blueprint total/formalized/proved; lean total/without-sorry/"
        "trust-boundary). Writes burnup-split.svg. Diagnostic; the pooled "
        "three-category chart is what the docs and the dashboard use.",
    )
    p.add_argument(
        "--in-progress",
        action="store_true",
        help=argparse.SUPPRESS,  # in-progress is now a default category; kept as a no-op
    )
    p.add_argument(
        "--combined",
        action="store_true",
        help=argparse.SUPPRESS,  # pooling is now the default for lean/leanblueprint
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any sample violates `tracked >= completed` or "
        "`tracked >= in-progress` (the warning is stamped into the SVG either way).",
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
    requested = {f: getattr(args, f) for f in OVERLAY_FLAGS}
    applicable = APPLICABLE_OVERLAYS.get(pipeline, APPLICABLE_OVERLAYS["verus"])
    if withheld := sorted(f for f, on in requested.items() if on and f not in applicable):
        print(
            f"[note] --{', --'.join(withheld)}: not applicable to pipeline {pipeline!r}; ignored.",
            file=sys.stderr,
        )
    overlays = Overlays(**{f: on and f in applicable for f, on in requested.items()})
    if args.in_progress:
        print(
            "[note] in-progress is a default category now; --in-progress is a no-op.",
            file=sys.stderr,
        )
    if args.combined:
        print(
            "[note] pooling definitions and theorems is the default now; "
            "--combined is a no-op (pass --split for the two-panel layout).",
            file=sys.stderr,
        )
    if args.split and pipeline not in ("leanblueprint", "lean"):
        print(
            f"[error] --split needs a leanblueprint or lean history; pipeline is {pipeline!r}.",
            file=sys.stderr,
        )
        return 2

    if pipeline in ("leanblueprint", "lean") and not args.split:
        # Refuse to plot silent-zero curves on a history predating the columns:
        # check the raw rows (pre-coercion), so absent != 0.
        is_bp = pipeline == "leanblueprint"
        needed = BP_POOLED_FIELDS if is_bp else LEAN_POOLED_FIELDS
        raw_ok = [r for r in _read_rows(args.input) if r.get("status") == "ok"]
        missing = sorted(
            r.get("sample_date", "?") for r in raw_ok if not all(_present(r, f) for f in needed)
        )
        if missing:
            example = (
                "bp_def_verified, bp_thm_verified, ..."
                if is_bp
                else "lean_def_total, lean_thm_sorry, ..."
            )
            print(
                f"[error] the pooled chart needs the per-{'node' if is_bp else 'kind'} "
                f"status columns ({example}), absent for samples: {', '.join(missing)}. "
                "Re-extract this history to populate them, or pass --split.",
                file=sys.stderr,
            )
            return 2
        # The unit and the proof-status provenance go in the subtitle so they are
        # always on the chart (see "How to read the charts" in the README).
        unit = "blueprint node" if is_bp else "declaration"
        render = bp_pooled_svg if is_bp else lean_pooled_svg
        result = render(
            ok,
            args.title or repo,
            f"{subtitle} · unit: {unit} · proof status: probe-lean",
            overlays,
        )
    elif args.split:
        if any(requested.values()):
            print(
                "[note] the overlay flags shape the pooled chart; --split draws each "
                "pipeline's own fixed vocabulary instead, so they are ignored.",
                file=sys.stderr,
            )
        render = blueprint_svg if pipeline == "leanblueprint" else lean_svg
        result = render(ok, args.title or repo, subtitle)
    else:
        result = burnup_svg(ok, args.title or f"{repo} — verification burn-up", subtitle, overlays)
    # Default alongside the input: data/<name>/progress.jsonl -> .../burnup.svg.
    # --split writes a distinct stem so it never overwrites the default chart.
    kind = "burnup-split" if args.split else "burnup"
    default_stem = kind if args.input.stem == "progress" else f"{args.input.stem}-{kind}"
    out = args.output or args.input.with_name(f"{default_stem}.svg")
    out.write_text(result.svg)
    print(f"wrote {out}")
    if args.png:
        svg_to_png(out, out.with_suffix(".png"), args.png_scale)
    for n in result.notes:
        print(f"[note] {n}", file=sys.stderr)
    for w in result.warnings:
        print(f"[warn] {w}", file=sys.stderr)
    if result.warnings and args.strict:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

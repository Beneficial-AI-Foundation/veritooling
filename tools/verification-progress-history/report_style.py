"""Shared palette/CSS tokens for the blueprint HTML reports.

Values are the validated palette from the project's dataviz skill (status
colors + chart chrome/ink, run through its palette validator, not eyeballed).
Both ``blueprint_dashboard.py`` and ``blueprint_insights.py``'s ``--html`` mode
import these so the two pages read as one system rather than drifting to their
own one-off hex codes.
"""

from __future__ import annotations

# Status palette (fixed -- never themed; light-surface hexes). Reserved for
# state, never reused as a categorical "series N" color.
GOOD = "#0ca30c"
WARNING = "#fab219"
SERIOUS = "#ec835a"
CRITICAL = "#d03b3b"

# Chart chrome & ink (light surface).
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"

# `warning` (#fab219) is sub-3:1 on a light surface by design (see palette.md) --
# never use it as plain text color, only as a swatch/fill paired with a label.
# This is a darker step of the same hue, safe for inline emphasized text.
WARNING_TEXT = "#a36a00"

BASE_CSS = f"""
body {{
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  margin: 2rem; color: {INK_PRIMARY}; background: {PAGE};
}}
h1 {{ font-size: 1.4rem; }}
h2 {{ font-size: 1.05rem; margin-top: 2rem; }}
caption {{ text-align: left; font-weight: 600; margin-bottom: .4rem; }}
table {{ border-collapse: collapse; margin: 1rem 0; background: {SURFACE}; }}
th, td {{ border: 1px solid {GRIDLINE}; padding: .35rem .7rem; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ background: #f4f4f6; color: {INK_SECONDARY}; font-weight: 600; }}
td.mv {{ font-weight: 600; color: {GOOD}; }}
td.warn {{ font-weight: 600; color: {CRITICAL}; }}
td.commit {{ font-family: ui-monospace, monospace; color: {INK_MUTED}; }}
.note {{ color: {INK_SECONDARY}; font-size: .9rem; max-width: 46rem; }}
"""

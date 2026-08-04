#!/usr/bin/env python3
"""Capture the verso-blueprint reference-blueprint screenshots used in
``guides/verso-blueprint-comparison.md``.

One-off capture helper, NOT part of the stdlib-only tool. It needs Playwright
and a Chromium build:

    pip install playwright && python -m playwright install chromium
    python capture_verso_screenshots.py            # writes *.verso-*.png here

Two shots per project:

* ``<proj>.verso-summary-overview.png`` -- element screenshot of just the
  "Overview" card on the Blueprint-Summary page (collapse everything else so the
  full 160+ row entry index does not overflow Chromium's max screenshot height).
* ``<proj>.verso-depgraph.png`` -- full-page shot of the Dependency-Graph page,
  after the d3 graph has rendered (wait for the ``svg`` node plus a settle).

Counts on the summary page are server-rendered, so they are exact reads. The
graph is d3, so it needs JS execution and a wait.
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://leanprover.github.io/verso-blueprint/reference-blueprints"

# project -> "<release>/<slug>" (verso pins these; see README.md provenance)
PROJECTS = {
    "carleson": "v4.31.0/verso-carleson",
    "sphere-packing": "v4.31.0/spherepackingblueprint",
    "flt": "v4.32.0/verso-flt",
    "noperthedron": "v4.32.0/noperthedron",
}

OUT = Path(__file__).parent


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1500, "height": 1000}, device_scale_factor=2)
        page = ctx.new_page()
        for name, slug in PROJECTS.items():
            # Summary: open only the Overview card, element-screenshot it.
            page.goto(
                f"{BASE}/{slug}/Blueprint-Summary/",
                wait_until="networkidle",
                timeout=60000,
            )
            page.evaluate(
                "document.querySelectorAll('details').forEach(d=>{"
                "const s=(d.querySelector('summary')||{}).textContent||'';"
                "d.open=/Overview/i.test(s);})"
            )
            time.sleep(1)
            card = page.query_selector(
                "xpath=//details[.//summary[contains(.,'Overview')]]"
            ) or page.query_selector("main")
            card.screenshot(path=str(OUT / f"{name}.verso-summary-overview.png"))

            # Dependency graph: wait for d3 to draw, then full-page shot.
            page.goto(
                f"{BASE}/{slug}/Dependency-Graph/",
                wait_until="networkidle",
                timeout=60000,
            )
            page.wait_for_selector("svg", timeout=30000)
            time.sleep(4)
            page.screenshot(path=str(OUT / f"{name}.verso-depgraph.png"), full_page=True)
            print(f"captured {name}")
        browser.close()


if __name__ == "__main__":
    main()

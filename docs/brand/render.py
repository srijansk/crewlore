#!/usr/bin/env python3
"""Render the crewlore wordmark PNGs and the GitHub social-preview card from wordmark.html.

Outputs, all under docs/assets/:
  logo-dark.png        white "crew" + teal "lore" on a transparent background (dark themes)
  logo-light.png       ink "crew" + teal "lore" on a transparent background (light themes)
  social-preview.png   1280x640 card for the repository's Settings -> Social preview (gitignored)

Requires Google Chrome and `uv` (which fetches Playwright on the fly):
  uv run --with playwright python docs/brand/render.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "wordmark.html"
ASSETS = HERE.parent / "assets"


def main() -> None:
    from playwright.sync_api import sync_playwright

    ASSETS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        # 2x for the logos so they stay crisp on high-density displays at any README width.
        page = browser.new_page(viewport={"width": 1400, "height": 1200}, device_scale_factor=2)
        page.goto(HTML.as_uri())
        page.evaluate("document.fonts.ready")
        for name in ("logo-dark", "logo-light"):
            page.locator(f"#{name}").screenshot(
                path=str(ASSETS / f"{name}.png"), omit_background=True
            )
        browser.close()
        # The card is rendered at 1x: 1280x640 is exactly what GitHub asks for.
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1200}, device_scale_factor=1)
        page.goto(HTML.as_uri())
        page.evaluate("document.fonts.ready")
        page.locator("#card").screenshot(path=str(ASSETS / "social-preview.png"))
        browser.close()
    for name in ("logo-dark.png", "logo-light.png", "social-preview.png"):
        path = ASSETS / name
        print(f"{path} ({path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

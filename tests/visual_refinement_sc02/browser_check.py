"""One-off real Chrome check against the owned loopback SC02 service."""
from pathlib import Path
import json
import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    base = sys.argv[1]
    root = Path(__file__).resolve().parents[2]
    evidence = root / "docs" / "visual_refinement" / "sc02" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True, args=["--no-first-run", "--no-default-browser-check"])
        context = browser.new_context(viewport={"width": 1536, "height": 1024}, device_scale_factor=1)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#main-image').naturalWidth > 0", timeout=30000)
        page.wait_for_timeout(1200)
        layout = page.evaluate("""() => ({
          viewport: [innerWidth, innerHeight],
          scrollWidth: document.documentElement.scrollWidth,
          scrollHeight: document.documentElement.scrollHeight,
          panels: [...document.querySelectorAll('.panel')].map(e => ({
            className: e.className, x: e.getBoundingClientRect().x,
            y: e.getBoundingClientRect().y, w: e.getBoundingClientRect().width,
            h: e.getBoundingClientRect().height
          })),
          maskWidth: document.querySelector('#main-image').naturalWidth,
          keyWidth: document.querySelector('#pipe-keyframe').naturalWidth,
          receipt: document.body.dataset.receipt || null,
          error: document.body.dataset.error || null,
          badge: document.querySelector('.header-status').innerText,
          winner: document.querySelector('#winner-card').innerText,
          videoDuration: document.querySelector('#player').duration
        })""")
        page.screenshot(path=str(evidence / "real-live-1536.png"), full_page=True)
        assert not errors, errors
        assert layout["scrollWidth"] <= 1536, layout
        assert layout["maskWidth"] == layout["keyWidth"] == 672, layout
        assert layout["receipt"] == "accepted", layout
        assert "Jev採用なし" in layout["winner"], layout
        for width, height in ((1280, 900), (1905, 867)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(250)
            size = page.evaluate("""() => ({width: innerWidth,
                scroll: document.documentElement.scrollWidth,
                panels: [...document.querySelectorAll('.panel')].map(e => {
                    const r=e.getBoundingClientRect(); return [r.x,r.y,r.right,r.bottom];})})""")
            assert size["scroll"] <= width, size
            assert all(x >= -0.5 and right <= width + 0.5 for x,y,right,bottom in size["panels"]), size
            print(json.dumps({"responsive": size}, ensure_ascii=True))
        print(json.dumps(layout, ensure_ascii=True))
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

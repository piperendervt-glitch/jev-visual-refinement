"""Real Chrome check for persisted SC02 replay without inference or writes."""
from pathlib import Path
import json
import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    base = sys.argv[1]
    evidence = Path(__file__).resolve().parents[2] / "docs/visual_refinement/sc02/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True, args=["--no-first-run", "--no-default-browser-check"])
        context = browser.new_context(viewport={"width": 1536, "height": 1024}, device_scale_factor=1)
        page = context.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#main-image').naturalWidth > 0", timeout=30000)
        current = page.evaluate("""() => ({
            badge: document.querySelector('#run-badge').innerText,
            playerHidden: document.querySelector('#player').hidden,
            savedKWidth: document.querySelector('#keyframe-image').naturalWidth,
            maskWidth: document.querySelector('#main-image').naturalWidth,
            disabled: document.querySelector('#analyze').disabled,
            winner: document.querySelector('#winner-card').innerText,
            receipt: document.body.dataset.receipt || null,
            jobs: document.querySelector("#queues").innerText
        })""")
        assert "SERVICE_STOPPED_NORMAL" in current["badge"], current
        assert current["playerHidden"] and current["disabled"], current
        assert page.locator("#reset").is_disabled()
        assert current["savedKWidth"] == current["maskWidth"] == 672, current
        assert "Jev採用なし" in current["winner"], current
        assert current["receipt"] is None, current
        assert "3/12" in current["jobs"], current
        page.screenshot(path=str(evidence / "real-saved-1536.png"), full_page=True)
        page.locator("#prev-k").click()
        page.wait_for_timeout(300)
        first = page.evaluate("""() => ({pts: document.querySelector('#pts').innerText,
            frame: document.querySelector('#frame-id').innerText,
            keyWidth: document.querySelector('#keyframe-image').naturalWidth,
            maskWidth: document.querySelector('#main-image').naturalWidth,
            receipt: document.body.dataset.receipt || null})""")
        assert "6144" in first["pts"] and first["frame"].startswith("k_1_"), first
        assert first["keyWidth"] == first["maskWidth"] == 672 and first["receipt"] is None, first
        page.screenshot(path=str(evidence / "real-first-k-1536.png"), full_page=True)
        page.locator("#next-k").click()
        page.wait_for_timeout(300)
        assert page.locator("#frame-id").inner_text().startswith("k_2_")
        nodes = page.locator("#timeline button")
        assert nodes.count() >= 2
        nodes.first.click()
        page.wait_for_timeout(250)
        historical = page.locator("#timeline-mode").inner_text()
        page.locator("details.fixture-tools summary").click()
        page.locator("#current").click()
        page.wait_for_timeout(300)
        assert "#" not in page.locator("#timeline-mode").inner_text()
        print(json.dumps({"saved": current, "historical": historical, "first": first}, ensure_ascii=True))
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

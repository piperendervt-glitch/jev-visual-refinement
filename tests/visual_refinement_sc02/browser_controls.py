"""Real Chrome playback, seek, EOF, and idle reset against the approved source."""
import json
import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    base = sys.argv[1]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True, args=["--no-first-run", "--no-default-browser-check"])
        context = browser.new_context(viewport={"width": 1536, "height": 1024}, device_scale_factor=1)
        page = context.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.locator("#player").evaluate("e => new Promise(r => e.readyState ? r() : e.addEventListener('loadedmetadata', r, {once:true}))")
        duration = page.locator("#player").evaluate("e => e.duration")
        assert 6 < duration < 7, duration
        page.locator("#play").click()
        page.wait_for_timeout(250)
        page.locator("#pause").click()
        assert page.locator("#player").evaluate("e => e.paused")
        page.locator("#player").evaluate("(e,t) => e.currentTime=t", duration - 0.08)
        page.locator("#play").click()
        page.wait_for_timeout(600)
        ended = page.locator("#player").evaluate("e => e.ended")
        assert ended, ended
        page.locator("details.fixture-tools summary").click()
        page.locator("#reset").click()
        page.wait_for_timeout(200)
        snapshot = page.request.get(base + "/api/sc02/snapshot").json()
        assert any(e["kind"] == "RunReset" for e in snapshot["events"]), snapshot
        assert snapshot["selected_count"] == snapshot["job_count"] == 0, snapshot
        assert not snapshot["frames"] and not snapshot["candidates"], snapshot
        assert page.locator("#stop-analysis").is_disabled()
        print(json.dumps({"duration": duration, "ended": ended,
                          "reset": True, "jobs": snapshot["job_count"]}, ensure_ascii=True))
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

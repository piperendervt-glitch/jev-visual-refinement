"""Exercise playback, a second K, saved cursor and failed-image receipt in real Chrome."""
from pathlib import Path
import json
import sqlite3
import sys
import time

from playwright.sync_api import sync_playwright


def main() -> int:
    base = sys.argv[1]
    root = Path(__file__).resolve().parents[2]
    evidence = root / "docs" / "visual_refinement" / "sc02" / "evidence"
    db = root / "runs" / "sc02" / "run_sc02_20260923_01" / "state.sqlite3"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True, args=["--no-first-run", "--no-default-browser-check"])
        context = browser.new_context(viewport={"width": 1536, "height": 1024}, device_scale_factor=1)
        page = context.new_page()
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#main-image').naturalWidth > 0")
        page.locator("#play").click()
        page.wait_for_timeout(300)
        page.locator("#pause").click()
        assert page.evaluate("document.querySelector('#player').paused")
        page.evaluate("document.querySelector('#player').currentTime=2")
        page.wait_for_function("Math.abs(document.querySelector('#player').currentTime-2)<0.05")
        existing = page.request.get(base + "/api/sc02/snapshot").json()
        if len(existing["frames"]) < 2:
            page.locator("#analyze").click()
        started = time.perf_counter()
        response = page.request.get(base + "/api/sc02/snapshot")
        latency_ms = (time.perf_counter() - started) * 1000
        assert response.ok and latency_ms < 1000, latency_ms
        page.locator("#play").click()
        page.locator("#pause").click()
        page.wait_for_function("document.querySelector('#main-image').naturalWidth > 0 && document.querySelector('#frame-id').innerText.startsWith('k_2_')", timeout=30000)
        page.wait_for_function("document.body.dataset.receipt==='accepted'", timeout=10000)
        frame_id = page.locator("#frame-id").inner_text()
        page.locator("#thumbs .thumb[data-lane='S']").focus()
        page.wait_for_timeout(1400)
        focus_kept = page.evaluate("document.activeElement === document.querySelector('#thumbs .thumb[data-lane=S]')")
        assert focus_kept
        page.screenshot(path=str(evidence / "real-second-k-1536.png"), full_page=True)
        page.locator(".time-node").last.click()
        assert page.evaluate("state.cursor !== null")
        page.locator(".fixture-tools summary").click()
        page.locator("#current").click()
        page.wait_for_function("state.cursor===null")
        context.close()

        failed_context = browser.new_context(viewport={"width": 1536, "height": 1024}, device_scale_factor=1)
        failed_page = failed_context.new_page()
        failed_page.route("**/api/sc02/artifacts/*preview*", lambda route: route.abort())
        failed_page.goto(base, wait_until="domcontentloaded")
        failed_page.locator("#retry-image").wait_for(state="visible", timeout=10000)
        failed_session = failed_page.evaluate("state.session")
        with sqlite3.connect(db) as conn:
            before = conn.execute("SELECT COUNT(*) FROM receipts WHERE session_id=?", (failed_session,)).fetchone()[0]
        assert before == 0, before
        failed_page.screenshot(path=str(evidence / "real-image-failure-1536.png"), full_page=True)
        failed_page.unroute("**/api/sc02/artifacts/*preview*")
        failed_page.locator("#retry-image").click()
        for _ in range(30):
            if failed_page.evaluate("document.body.dataset.receipt") == "accepted":
                break
            failed_page.wait_for_timeout(300)
        assert failed_page.evaluate("document.body.dataset.receipt") == "accepted", failed_page.evaluate("({receipt:document.body.dataset.receipt,error:document.body.dataset.error,image:document.querySelector('#main-image').naturalWidth,retryHidden:document.querySelector('#retry-image').hidden})")
        with sqlite3.connect(db) as conn:
            after = conn.execute("SELECT COUNT(*) FROM receipts WHERE session_id=?", (failed_session,)).fetchone()[0]
        assert after == 1, after
        failed_context.close()
        browser.close()
    print(json.dumps({"second_frame": frame_id, "status_latency_ms": round(latency_ms, 1),
                      "focus_kept": focus_kept, "failed_image_receipts_before": before,
                      "after_retry": after}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Owned Chrome/Playwright fixture check for the seven-panel live projection.

Run with the repository .venv. No model, media, GPU, Jev, or browser download.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re
import shutil
import tempfile
import threading
import sys
from urllib.parse import urlsplit

import numpy as np
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.visual_refinement_sc02.masks import overlay_png, png_mask, png_rgb
from src.visual_refinement_live import analysis, store as store_module
from src.visual_refinement_live import server as server_module
from src.visual_refinement_live.evaluation import SelectionEngine
from src.visual_refinement_live.jev_wire import AXES, CRITERIA
from src.visual_refinement_live.server import LiveServer
from src.visual_refinement_live.store import LiveStore

REPO = Path(__file__).resolve().parents[2]
ROOT = (REPO / "cache" / "sc03_sc07").resolve()
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
SOURCE_HASH = "a" * 64
RUN_ID = "browser_fixture"
FRAME_ID = "k_fixture"


def score_response(q: int) -> bytes:
    answers = {}
    for axis in AXES:
        score = q if axis == "Q" else 2
        answers[axis] = {"type": "score", "score": score, "confidence": 1,
                         "legend": {str(i): CRITERIA[axis][i] for i in range(5)},
                         "probabilities": {str(i): int(i == score) for i in range(5)}}
    return json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": None},
                       "answers": answers}).encode()


class FixtureController:
    def __init__(self, store: LiveStore):
        self.store = store
        self.video = None
        self.accepting = False

    def snapshot(self, cursor=None):
        view = self.store.snapshot(cursor)
        view.update({"accepting": False, "worker_alive": False, "selected_count": 1,
                     "max_keyframes": 2, "active_phase": None, "failure": None})
        return view


class FixtureBatchStub:
    """Browser transport contract only; no segmentation or evaluation work."""

    def __init__(self):
        self.seconds = [0.5, 2.0]
        self.planned = None
        self.started = None

    def k_set(self):
        return {"seconds": self.seconds, "allowed_seconds": [0.5, 2.0]}

    def save_k_set(self, seconds):
        self.seconds = list(seconds)
        return self.k_set()

    def plan(self, *, profiles, repeats, k_seconds, bucket):
        self.planned = (profiles, repeats, k_seconds, bucket)
        return {"run_count": len(profiles) * repeats,
                "segmentation_jobs": len(profiles) * len(k_seconds) * repeats,
                "e0_suites": 1, "e1_suites": 0, "max_http_attempts": 1,
                "max_reserved_micro_usd": 0,
                "ledger_before": {"gpu_jobs": 0}}

    def start(self, *, profiles, repeats, k_seconds, bucket):
        self.started = (profiles, repeats, k_seconds, bucket)
        return {"batch_id": "fixture_transport_only",
                "plan": self.plan(profiles=profiles, repeats=repeats,
                                  k_seconds=k_seconds, bucket=bucket)}

    def status(self):
        return {"active_batch_id": None, "batches": [], "runs": []}


def main() -> None:
    if not CHROME.is_file():
        raise RuntimeError("existing_chrome_missing")
    ROOT.mkdir(parents=True, exist_ok=True)
    owned = Path(tempfile.mkdtemp(prefix="browser_fixture_runs_", dir=ROOT)).resolve()
    profile = Path(tempfile.mkdtemp(prefix="browser_profile_", dir=ROOT)).resolve()
    for target in (owned, profile):
        if not target.is_relative_to(ROOT) or target == ROOT or target.is_symlink():
            raise RuntimeError("owned_path_invalid")
    evidence = ROOT / "browser_evidence"
    evidence.mkdir(exist_ok=True)
    store_module.RUNS_ROOT = owned
    analysis.RUNS_ROOT = owned
    server_module.analysis_snapshot = lambda: analysis.analysis_snapshot(owned)
    server_module.compare_runs = lambda: analysis.compare_runs(owned)
    writer = None
    server = None
    thread = None
    context = None
    try:
        writer = LiveStore(RUN_ID, create=True, source={"source_id": "fixture-source",
                            "filename": "synthetic_fixture.mp4"},
                           experiment={"origin": "FIXTURE", "profile": "SABC", "jev": False})
        rgb = np.zeros((448, 672, 3), np.uint8)
        rgb[:, :, 0] = 18
        rgb[:, :, 1] = 48
        rgb[:, :, 2] = 75
        rgb[85:360, 180:500] = (205, 128, 64)
        key = writer.put_artifact("key", ".png", png_rgb(rgb), "image/png")
        writer.event("KeyframeRequested", FRAME_ID, None, {"requested_seconds": 0.5})
        writer.frame(FRAME_ID, {"frame_id": FRAME_ID, "requested_seconds": 0.5,
                                "actual_seconds": 0.5, "pts": 500, "time_base": [1, 1000],
                                "sample_id": "synthetic", "pixel_sha256": SOURCE_HASH,
                                "image_artifact_id": key["artifact_id"],
                                "width": 672, "height": 448})
        writer.evidence("e_k0", FRAME_ID, 0,
                        {"evidence_id": "e_k0", "frame_id": FRAME_ID, "version": 0})
        engine = SelectionEngine(writer)

        def candidate(lane: str, shift: int = 0) -> str:
            ident = f"cand_k_{lane.lower()}"
            mask = np.zeros((448, 672), np.uint8)
            mask[95 + shift:345 + shift, 190 + shift:470 + shift] = 1
            mask_art = writer.put_artifact(f"mask_{lane.lower()}", ".png",
                                           png_mask(mask), "image/png")
            preview = writer.put_artifact(f"preview_{lane.lower()}", ".png",
                                          overlay_png(rgb, mask[None, :, :]), "image/png")
            writer.candidate(ident, FRAME_ID, lane,
                {"candidate_id": ident, "frame_id": FRAME_ID, "lane_id": lane,
                 "origin": "FIXTURE", "architecture_label": f"FIXTURE-{lane}",
                 "segmentation_status": "SUCCEEDED_NONEMPTY", "mask_count": 1,
                 "masks": [{"artifact_id": mask_art["artifact_id"]}],
                 "preview_artifact_id": preview["artifact_id"],
                 "source_pixel_sha256": SOURCE_HASH, "device": "fixture-cpu"})
            return ident

        def evaluate(ident: str, lane: str, q: int, version: int) -> None:
            task = engine.ensure_task(FRAME_ID, ident, lane, version,
                                      sha256(f"{ident}:{version}".encode()).hexdigest(),
                                      origin="FIXTURE")
            job = f"job_{task}"
            writer.job(job, FRAME_ID, lane, "EVALUATION", "EVALUATION_SUITE")
            writer.job_state(job, "RUNNING", phase="FIXTURE_SCORE")
            outcome = engine.accept_attempt(task, f"att_{task}", score_response(q),
                                            origin="FIXTURE")
            assert set(outcome["accepted_axes"]) == set(AXES)
            writer.job_state(job, "SUCCEEDED")

        writer.job("seg_s", FRAME_ID, "S", "SEGMENTATION", "SEGMENTATION_JOB")
        writer.job_state("seg_s", "RUNNING", phase="FIXTURE_MASK")
        s_id = candidate("S")
        writer.job_state("seg_s", "SUCCEEDED")
        batch_stub = FixtureBatchStub()
        server = LiveServer(FixtureController(writer), ("127.0.0.1", 0),
                            batch_manager=batch_stub)
        thread = threading.Thread(target=server.serve_forever, daemon=False)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        violations = []
        page_errors = []
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile), executable_path=str(CHROME), headless=True,
                viewport={"width": 1536, "height": 1024}, device_scale_factor=1,
                args=["--disable-background-networking", "--disable-sync",
                      "--disable-extensions", "--no-first-run",
                      "--no-default-browser-check"])
            try:
                def route_guard(route):
                    address = urlsplit(route.request.url)
                    if address.scheme == "http" and address.hostname == "127.0.0.1" and address.port == server.server_port:
                        if address.path == "/api/live/video":
                            route.fulfill(status=204, body="")
                        else:
                            route.continue_()
                    else:
                        violations.append(route.request.url)
                        route.abort()
                context.route("**/*", route_guard)
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.goto(base + "/", wait_until="load")
                expect(page.locator("section.panel")).to_have_count(7)
                assert "FIXTURE" in page.locator("#header-mode").inner_text()
                assert page.locator("#lanes .pipe-lane").count() == 4
                assert page.locator("#queues").get_attribute("class") == "queue-detail normal"
                page.locator("#main-image").wait_for(state="visible")
                expect(page.locator("body")).to_have_attribute("data-receipt", "accepted")
                with writer.lock:
                    assert writer.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
                page.screenshot(path=str(evidence / "fixture_initial_1536.png"))
                print("BROWSER_FIXTURE initial_7_panels_and_receipt OK")

                writer.job("seg_a", FRAME_ID, "A", "SEGMENTATION", "SEGMENTATION_JOB")
                expect(page.locator("#queues")).to_have_class(re.compile(r"\battention\b"))
                assert page.locator(".flow-dot").count() == 0
                writer.job("seg_b", FRAME_ID, "B", "SEGMENTATION", "SEGMENTATION_JOB")
                expect(page.locator("#queues")).to_have_class(re.compile(r"\bcongested\b"))
                writer.job("seg_c", FRAME_ID, "C", "SEGMENTATION", "SEGMENTATION_JOB")
                expect(page.locator("#queues")).to_have_class(re.compile(r"\bsaturated\b"))
                print("BROWSER_FIXTURE queue_color_transitions OK")

                evaluate(s_id, "S", 3, 0)
                expect(page.locator("#winner-card")).to_contain_text("S")
                page.locator('.thumb[data-lane="S"]').click()
                expect(page.locator("#winner-card")).to_contain_text("S")
                assert page.locator('.thumb[data-lane="S"]:focus').count() == 1
                writer.job_state("seg_a", "RUNNING", phase="FIXTURE_MASK")
                context.route("**/api/live/artifacts/preview_a*", lambda route: route.abort())
                a_id = candidate("A", 7)
                writer.job_state("seg_a", "SUCCEEDED")
                expect(page.locator('#lanes .pipe-lane[data-lane="A"] .lane-stage')).to_contain_text("mask")
                page.locator(".flow-dot").first.wait_for(state="attached")
                expect(page.locator(".flow-dot")).to_have_count(0, timeout=3000)
                page.wait_for_timeout(750)
                assert page.locator(".flow-dot").count() == 0
                assert "fixture" in page.locator("#flow-note").inner_text().lower()
                evaluate(a_id, "A", 4, 0)
                expect(page.locator("#matrix tr[data-lane=A] .verdict")).to_contain_text("\u63a1\u7528")
                assert page.locator('.thumb[data-lane="S"]:focus').count() == 1
                assert "S" in page.locator("#winner-card").inner_text()
                with writer.lock:
                    before_failure = writer.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
                page.locator(".fixture-tools summary").click()
                page.locator("#current").click()
                page.locator("#retry-image").wait_for(state="visible")
                with writer.lock:
                    assert writer.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == before_failure
                context.unroute("**/api/live/artifacts/preview_a*")
                page.locator("#retry-image").click()
                expect(page.locator("#main-image")).to_have_attribute("data-failed", "false")
                with writer.lock:
                    assert writer.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] > before_failure
                print("BROWSER_FIXTURE q_revision_manual_focus_image_receipt OK")

                for lane, shift in (("B", 13), ("C", 20)):
                    job = f"seg_{lane.lower()}"
                    writer.job_state(job, "RUNNING", phase="FIXTURE_MASK")
                    candidate(lane, shift)
                    writer.job_state(job, "SUCCEEDED")
                expect(page.locator("#lanes .lane-stage").filter(has_text="mask")).to_have_count(4)
                expect(page.locator("#queues")).to_have_class(re.compile(r"\bnormal\b"))
                page.screenshot(path=str(evidence / "fixture_four_lanes_1536.png"))
                page.screenshot(path=str(evidence / "fixture_four_lanes_1536.jpg"), type="jpeg", quality=50)
                writer.evidence("e_k1", FRAME_ID, 1,
                                {"evidence_id": "e_k1", "frame_id": FRAME_ID,
                                 "version": 1, "previous_ref": "e_k0",
                                 "comparison_set_refs": [s_id, a_id]})
                expect(page.locator("#info-evidence")).to_contain_text("E1")
                assert "fallback" in page.locator("#winner-card").inner_text().lower() or "旧" in page.locator("#winner-card").inner_text()
                evaluate(s_id, "S", 4, 1)
                expect(page.locator("#winner-card")).to_contain_text("S")
                assert "E1" in page.locator("#info-evidence").inner_text()
                page.screenshot(path=str(evidence / "fixture_e1_1536.png"))
                page.screenshot(path=str(evidence / "fixture_e1_1536.jpg"), type="jpeg", quality=50)
                print("BROWSER_FIXTURE e1_fallback_refresh OK")

                page.locator(".experiment-tools summary").click()
                page.locator('.profile-check[value="SAB"]').uncheck()
                page.locator('.profile-check[value="SABC"]').uncheck()
                page.locator("#experiment-repeats").fill("1")
                page.locator('.k-check[value="2"]').uncheck()
                page.locator("#k-save").click()
                expect(page.locator("#experiment-result")).to_contain_text("0.5")
                page.locator('.k-check[value="2"]').check()
                page.locator("#k-load").click()
                expect(page.locator('.k-check[value="2"]')).not_to_be_checked()
                page.locator("#experiment-plan").click()
                expect(page.locator("#experiment-result")).to_contain_text("1 run")
                assert batch_stub.planned == (("S",), 1, (0.5,), "VALIDATION")
                page.locator("#experiment-start").click()
                expect(page.locator("#experiment-result")).to_contain_text(
                    "fixture_transport_only")
                assert batch_stub.started == (("S",), 1, (0.5,), "VALIDATION")
                print("BROWSER_FIXTURE batch_plan_start_ui_transport OK")
                timeline = page.locator("#timeline .time-node")
                assert timeline.count() > 1
                timeline.first.click()
                expect(page.locator("#timeline-mode")).to_contain_text("#")
                page.locator("#current").click()
                expect(page.locator("#timeline-mode")).not_to_contain_text("#")
                writer.close_run("COMPLETE_NONEMPTY", normal=True)
                expect(page.locator("#info-run")).to_contain_text("COMPLETE_NONEMPTY")
                with writer.lock:
                    original_seq = writer.snapshot()["snapshot_seq"]
                page.goto(base + "/?run=" + RUN_ID, wait_until="load")
                expect(page.locator("#main-image")).to_have_attribute("data-failed", "false")
                expect(page.locator("body")).to_have_attribute("data-receipt", "accepted")
                assert server.view_sessions.count(RUN_ID) >= 1
                assert writer.snapshot()["snapshot_seq"] == original_seq
                page.locator(".fixture-tools summary").click()
                page.locator("#timeline .time-node").first.click()
                expect(page.locator("#timeline-mode")).to_contain_text("#")
                page.locator("#current").click()
                expect(page.locator("#timeline-mode")).not_to_contain_text("#")
                expect(page.locator("#main-image")).to_have_attribute("data-failed", "false")
                assert writer.snapshot()["snapshot_seq"] == original_seq
                page.locator(".experiment-tools summary").click()
                page.locator("#experiment-list").click()
                expect(page.locator("#experiment-result")).to_contain_text("browser_fixture")
                page.locator("#experiment-compare").click()
                expect(page.locator("#experiment-result")).to_contain_text("\u5168\u5bfe\u8c61")
                page.screenshot(path=str(evidence / "fixture_saved_compare_1536.png"))
                page.screenshot(path=str(evidence / "fixture_saved_compare_1536.jpg"), type="jpeg", quality=50)
                assert not violations, f"browser_outside_loopback:{len(violations)}"
                assert not page_errors, f"page_errors:{page_errors}"
                print("BROWSER_FIXTURE replay_cursor_compare_shutdown OK")
                page.locator("#shutdown").click()
                thread.join(timeout=5)
                assert not thread.is_alive()
                print("BROWSER_FIXTURE ALL_PASS")
            finally:
                if context is not None:
                    closing = context
                    context = None
                    closing.close()
    finally:
        if server is not None:
            server.shutdown()
            if thread is not None:
                thread.join(timeout=5)
            server.server_close()
        if writer is not None:
            writer.close()
        for target in (profile, owned):
            if not target.is_relative_to(ROOT) or target == ROOT or target.is_symlink():
                raise RuntimeError("cleanup_outside_owned_root")
            shutil.rmtree(target)


if __name__ == "__main__":
    main()

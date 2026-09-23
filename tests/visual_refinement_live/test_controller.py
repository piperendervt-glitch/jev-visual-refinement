"""SC03 end-to-end lane scheduling with injected segmenters and keyframe."""
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pytest

from src.visual_refinement_sc02.segmenter import SegmentOutput
from src.visual_refinement_live import controller as live_controller
from src.visual_refinement_live import store as live_store
from src.visual_refinement_live.segmenters import ModelProvenance


def test_four_independent_lanes_publish_initial_then_real_supplementary(tmp_path, monkeypatch):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "runs")
    rgb = np.zeros((16, 16, 3), np.uint8)
    rgb[2:10, 2:10] = 255
    video = SimpleNamespace(source_id="synthetic", path=Path("synthetic.mp4"),
                            display_width=16, display_height=16, duration_seconds=3,
                            byte_count=100, codec="h264")
    decoded = SimpleNamespace(rgb=rgb, pts=6144, time_base_num=1, time_base_den=12288,
                              actual_seconds=0.5, sample_id="synthetic-k",
                              width=16, height=16, pixel_sha256="a" * 64)
    monkeypatch.setattr(live_controller, "probe_video", lambda _: video)
    monkeypatch.setattr(live_controller, "decode_at", lambda _video, _seconds: decoded)

    class FakeAdapter:
        torch = None
        def __init__(self, lane):
            self.lane = lane
            self.provenance = ModelProvenance(lane, f"FAKE-{lane}", "fixture-revision",
                                              "a" * 64, 42, "TEST_ONLY", "cuda:0", 1.0)
        def predict(self, image):
            time.sleep({"S": 0.04, "A": 0.03, "B": 0.02, "C": 0.01}[self.lane])
            mask = np.zeros((1, 16, 16), np.uint8)
            mask[0, 2:10, 2:10] = 1
            return SegmentOutput(mask, mask, np.array([[2, 2, 10, 10]], np.float32),
                                 np.array([0], np.float32), np.array([0.8], np.float32),
                                 "cuda:0", {"preprocess": 1.0, "inference": 2.0,
                                            "postprocess": 1.0, "synchronized_predict_total": 4.0})
        def close(self):
            pass

    run = live_controller.LiveController(video=Path("synthetic.mp4"), run_id="fixture_run",
                                         lanes=("S", "A", "B", "C"),
                                         adapter_factory=FakeAdapter, origin="FIXTURE")
    frame_id = run.select(0.5)
    run.worker.join(timeout=10)
    view = run.snapshot()
    assert not view["worker_alive"]
    assert len(view["candidates"]) == 4
    assert {x["lane_id"] for x in view["candidates"]} == set("SABC")
    assert all(x["origin"] == "FIXTURE" for x in view["candidates"])
    assert len([x for x in view["measurements"] if x["kind"] == "INITIAL"]) == 4
    assert len([x for x in view["measurements"] if x["kind"] == "SUPPLEMENTARY"]) == 1
    assert [x["version"] for x in view["evidence"]] == [0, 1]
    assert len([x for x in view["jobs"] if x["unit"] == "SEGMENTATION_JOB"]) == 4
    assert all(x["status"] == "SUCCEEDED" for x in view["jobs"])
    assert all(x["frame_id"] == frame_id for x in view["candidates"])
    assert run.close()["normal"]
    saved = live_controller.LiveController(video=None, run_id="fixture_run", lanes=("S", "A", "B", "C"),
                                           open_existing=True)
    assert len(saved.snapshot()["candidates"]) == 4
    assert saved.close()["normal"]


def test_evaluation_budget_stop_preserves_completed_masks_and_e1(tmp_path, monkeypatch):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "runs")
    rgb = np.zeros((8, 8, 3), np.uint8)
    video = SimpleNamespace(source_id="synthetic", path=Path("synthetic.mp4"),
                            display_width=8, display_height=8,
                            duration_seconds=3, byte_count=50, codec="h264")
    decoded = SimpleNamespace(rgb=rgb, pts=500, time_base_num=1, time_base_den=1000,
                              actual_seconds=0.5, sample_id="sample",
                              width=8, height=8, pixel_sha256="a" * 64)
    monkeypatch.setattr(live_controller, "probe_video", lambda _: video)
    monkeypatch.setattr(live_controller, "decode_at", lambda _v, _s: decoded)

    class Adapter:
        torch = None
        def __init__(self, lane):
            self.provenance = ModelProvenance(lane, f"FIXTURE-{lane}", "fixture",
                                              "a" * 64, 42, "TEST_ONLY", "cuda:0", 1.0)
        def predict(self, _image):
            mask = np.zeros((1, 8, 8), np.uint8)
            mask[0, 2:6, 2:6] = 1
            return SegmentOutput(mask, mask, np.array([[2, 2, 6, 6]], np.float32),
                                 np.array([0], np.float32),
                                 np.array([0.8], np.float32), "cuda:0",
                                 {"preprocess": 1.0, "inference": 1.0,
                                  "postprocess": 1.0})
        def close(self):
            pass

    class BudgetStop:
        def enqueue(self, *_args, **_kwargs):
            raise ValueError("suite_budget")
        def has_pending(self):
            return False
        def close(self):
            pass

    run = live_controller.LiveController(video=Path("synthetic.mp4"),
                                         run_id="budget_fixture", lanes=("S", "A"),
                                         adapter_factory=Adapter, evaluator=BudgetStop(),
                                         origin="FIXTURE")
    run.select(0.5)
    run.worker.join(timeout=10)
    view = run.snapshot()
    assert len(view["candidates"]) == 2
    assert {x["version"] for x in view["evidence"]} == {0, 1}
    assert all(x["status"] == "SUCCEEDED" for x in view["jobs"]
               if x["stage"] == "SEGMENTATION")
    assert len([x for x in view["jobs"] if x["error_code"] == "BUDGET_STOP"]) == 4
    assert run.close()["business"] == "PARTIAL_FAILURE"


@pytest.mark.parametrize("failure", ("cleanup", "measurement"))
def test_lane_failure_after_gpu_start_is_terminal_and_accounted(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "runs")
    rgb = np.zeros((8, 8, 3), np.uint8)
    video = SimpleNamespace(source_id="synthetic", path=Path("synthetic.mp4"),
                            display_width=8, display_height=8, duration_seconds=3,
                            byte_count=50, codec="h264")
    decoded = SimpleNamespace(rgb=rgb, pts=500, time_base_num=1, time_base_den=1000,
                              actual_seconds=0.5, sample_id="sample",
                              width=8, height=8, pixel_sha256="a" * 64)
    monkeypatch.setattr(live_controller, "probe_video", lambda _: video)
    monkeypatch.setattr(live_controller, "decode_at", lambda _v, _s: decoded)

    class Adapter:
        torch = None

        def __init__(self, lane):
            self.provenance = ModelProvenance(lane, "FIXTURE-S", "fixture",
                                              "a" * 64, 42, "TEST_ONLY", "cuda:0", 1.0)

        def predict(self, _image):
            mask = np.zeros((1, 8, 8), np.uint8)
            mask[0, 2:6, 2:6] = 1
            return SegmentOutput(mask, mask, np.array([[2, 2, 6, 6]], np.float32),
                                 np.array([0], np.float32), np.array([0.8], np.float32),
                                 "cuda:0", {"synchronized_predict_total": 1.0})

        def close(self):
            if failure == "cleanup":
                raise RuntimeError("fixture_cleanup_failure")

    class Ledger:
        def __init__(self):
            self.marked = []

        def reserve_gpu_job(self, **_kwargs):
            pass

        def mark_gpu_job(self, job_id, duration_ms):
            self.marked.append((job_id, duration_ms))

    if failure == "measurement":
        def fail_measure(*_args, **_kwargs):
            raise RuntimeError("fixture_measurement_failure")
        monkeypatch.setattr(live_controller, "measure_candidate", fail_measure)
    ledger = Ledger()
    run = live_controller.LiveController(
        video=Path("synthetic.mp4"), run_id="post_gpu_fixture", lanes=("S",),
        adapter_factory=Adapter, job_ledger=ledger, origin="FIXTURE")
    run.select(0.5)
    run.worker.join(timeout=10)
    view = run.snapshot()
    segmentation = [x for x in view["jobs"] if x["stage"] == "SEGMENTATION"]
    assert len(segmentation) == 1
    assert segmentation[0]["status"] == "FAILED"
    assert segmentation[0]["error_code"].startswith("RuntimeError:fixture_")
    assert len(ledger.marked) == 1
    assert ledger.marked[0][0] == segmentation[0]["id"]
    assert any(x["kind"] == "LaneFailed" for x in view["events"])
    assert run.close()["normal"]

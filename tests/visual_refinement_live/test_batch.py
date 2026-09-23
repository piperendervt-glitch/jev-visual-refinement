"""Fixture-only end-to-end batch, ledger, replay index, and compare."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from src.visual_refinement_sc02.segmenter import SegmentOutput
from src.visual_refinement_live import batch as batch_module
from src.visual_refinement_live import controller as controller_module
from src.visual_refinement_live import analysis as analysis_module
from src.visual_refinement_live import store as store_module
from src.visual_refinement_live.analysis import analysis_snapshot, compare_runs
from src.visual_refinement_live.batch import BatchManager
from src.visual_refinement_live.ledger import BudgetLedger
from src.visual_refinement_live.segmenters import ModelProvenance
from test_jev_client import _raw


def test_fixture_batch_consumes_atomic_plan_and_indexes_all_runs(tmp_path, monkeypatch):
    owned = tmp_path / "owned"
    owned.mkdir()
    monkeypatch.setattr(store_module, "RUNS_ROOT", owned)
    monkeypatch.setattr(batch_module, "RUNS_ROOT", owned)
    monkeypatch.setattr(analysis_module, "RUNS_ROOT", owned)
    rgb = np.zeros((16, 16, 3), np.uint8)
    rgb[2:12, 2:12] = 200
    video = SimpleNamespace(source_id="fixture-source", path=Path("fixture.mp4"),
                            display_width=16, display_height=16,
                            duration_seconds=3, byte_count=100, codec="h264")
    monkeypatch.setattr(controller_module, "probe_video", lambda _: video)

    def decode(_video, seconds):
        return SimpleNamespace(rgb=rgb, pts=int(seconds * 1000),
                               time_base_num=1, time_base_den=1000,
                               actual_seconds=seconds, sample_id=f"k_{seconds}",
                               width=16, height=16,
                               pixel_sha256="a" * 64 if seconds == 0.5 else "b" * 64)
    monkeypatch.setattr(controller_module, "decode_at", decode)

    class Adapter:
        torch = None
        def __init__(self, lane):
            self.lane = lane
            self.provenance = ModelProvenance(
                lane, f"FIXTURE-{lane}", "fixture", "a" * 64, 42,
                "TEST_ONLY", "cuda:0", 1.0)
        def predict(self, image):
            mask = np.zeros((1, 16, 16), np.uint8)
            mask[0, 2:12, 2:12] = 1
            return SegmentOutput(mask, mask, np.array([[2, 2, 12, 12]], np.float32),
                                 np.array([0], np.float32),
                                 np.array([0.9], np.float32), "cuda:0",
                                 {"preprocess": 1.0, "inference": 1.0,
                                  "postprocess": 1.0, "synchronized_predict_total": 3.0})
        def close(self):
            pass

    class Transport:
        def send(self, _state, _axes):
            return _raw()

    ledger = BudgetLedger(owned / "budget.sqlite3")
    manager = BatchManager(Path("fixture.mp4"), ledger,
                           main_controller=SimpleNamespace(worker=None, evaluator=None, video=video),
                           origin="FIXTURE", adapter_factory=Adapter,
                           fixture_transport=Transport())
    try:
        plan = manager.plan(profiles=("S", "SAB"), repeats=1)
        assert plan["segmentation_jobs"] == 8
        assert plan["logical_suites"] == 14
        saved = manager.save_k_set((0.5, 2.0))
        assert saved["seconds"] == [0.5, 2.0]
        started = manager.start(profiles=("S", "SAB"), repeats=1)
        manager.worker.join(timeout=20)
        assert not manager.worker.is_alive()
        status = manager.status()
        assert status["batches"][0]["status"] == "COMPLETE"
        assert len(status["runs"]) == 2
        assert all(r["status"] == "COMPLETE_NONEMPTY" for r in status["runs"])
        counts = ledger.snapshot()
        assert counts["gpu_jobs"] == 8
        assert counts["suites"] == 14
        assert counts["http_attempts"] == 14
        assert counts["planned_remaining"]["gpu_jobs"] == 0
        index = analysis_snapshot(owned)
        assert index["all_target_run_count"] == 2
        assert len(index["excluded"]) == 2
        assert all(x["origin"] == "FIXTURE" for x in index["runs"])
        comparison = compare_runs(owned)
        assert comparison["saved_policy_comparison"] == []
        assert len(comparison["fixture_checks_excluded_from_live"]) == 2
        assert sum(len(x["saved_policy"]) for x in
                   comparison["fixture_checks_excluded_from_live"]) == 6
        assert comparison["actual_configuration_comparison"] == []
    finally:
        manager.close()
        ledger.close()



def test_restart_marks_abandoned_batch_and_keeps_spent_budget(tmp_path, monkeypatch):
    owned = tmp_path / "owned"
    owned.mkdir()
    monkeypatch.setattr(batch_module, "RUNS_ROOT", owned)
    ledger = BudgetLedger(owned / "budget.sqlite3")
    main = SimpleNamespace(worker=None, evaluator=None, video=object())
    first = BatchManager(Path("fixture.mp4"), ledger, main_controller=main,
                         origin="FIXTURE", adapter_factory=object(),
                         fixture_transport=object())
    ident = "abandoned"
    ledger.reserve_plan(plan_id=ident, definition_digest="digest", bucket="VALIDATION",
                        gpu_jobs=1, suites=1, http_attempts=2, questions=10,
                        body_bytes=65536, cost_micro=5376)
    ledger.reserve_gpu_job(run_id="run1", frame_id="k1", lane_id="S",
                           plan_id=ident, job_id="job1")
    first.db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)",
                     (ident, "digest", "{}", "VALIDATION", "RUNNING", 1, None, None))
    first.db.execute("INSERT INTO batch_runs VALUES(?,?,?,?,?,?)",
                     (ident, 1, "run1", "S", 1, "RUNNING"))
    first.db.commit()
    first.close()
    reopened = BatchManager(Path("fixture.mp4"), ledger, main_controller=main,
                            origin="FIXTURE", adapter_factory=object(),
                            fixture_transport=object())
    try:
        status = reopened.status()
        assert status["batches"][0]["status"] == "INTERRUPTED"
        assert status["runs"][0]["status"] == "INTERRUPTED"
        usage = ledger.snapshot()
        assert usage["gpu_jobs"] == 1
        assert usage["planned_remaining"]["suites"] == 0
    finally:
        reopened.close()
        ledger.close()

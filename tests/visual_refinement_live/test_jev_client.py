"""Evaluation worker reaches saved Decision through an injected transport."""
import json

import numpy as np

from src.visual_refinement_live import store as live_store
from src.visual_refinement_live.jev_client import JevEvaluator
from src.visual_refinement_live.jev_wire import AXES, CRITERIA
from src.visual_refinement_live.ledger import BudgetLedger
from src.visual_refinement_live.measurement import measure_candidate
from src.visual_refinement_live.store import LiveStore


def _raw():
    answers = {}
    for axis in AXES:
        score = 3 if axis == "Q" else 2
        answers[axis] = {"type": "score", "score": score, "confidence": 1.0,
                         "legend": {str(i): CRITERIA[axis][i] for i in range(5)},
                         "probabilities": {str(i): 1.0 if i == score else 0.0 for i in range(5)}}
    return json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 400},
                       "answers": answers}).encode()


def test_injected_transport_drives_saved_selection_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "owned")
    store = LiveStore("fixture", create=True)
    store.frame("k1", {"frame_id": "k1", "pixel_sha256": "a" * 64})
    store.evidence("e_k1_0", "k1", 0, {"evidence_id": "e_k1_0", "frame_id": "k1", "version": 0})
    preview = store.put_artifact("p", ".png", b"synthetic", "image/png")
    candidate = {"candidate_id": "cand_k1_s", "frame_id": "k1", "lane_id": "S",
                 "origin": "FIXTURE", "segmentation_status": "SUCCEEDED_EMPTY",
                 "mask_count": 0, "masks": [], "preview_artifact_id": preview["artifact_id"],
                 "source_pixel_sha256": "a" * 64}
    store.candidate("cand_k1_s", "k1", "S", candidate)
    measurement = measure_candidate(np.zeros((4, 4, 3), np.uint8),
                                    np.zeros((0, 4, 4), np.uint8))
    measurement["origin"] = "FIXTURE_MEASUREMENT"
    calls = []
    class FakeTransport:
        def send(self, state, axes):
            calls.append(axes)
            return _raw()
    ledger = BudgetLedger(tmp_path / "ledger.sqlite3")
    evaluator = JevEvaluator(store, ledger, transport=FakeTransport(), origin="FIXTURE")
    evaluator.enqueue("k1", candidate, measurement, evidence_version=0)
    evaluator.close()
    view = store.snapshot()
    assert calls == [AXES]
    assert view["selection"]["k1"]["winner_id"] == "cand_k1_s"
    assert view["decisions"][0]["origin"] == "FIXTURE"
    assert view["evaluations"][0]["origin"] == "FIXTURE"
    assert ledger.snapshot()["suites"] == 1
    assert ledger.snapshot()["http_attempts"] == 1
    ledger.close()
    store.close()


def test_real_transport_rejects_fixture_input_before_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "owned")
    store = LiveStore("fixture", create=True)
    ledger = BudgetLedger(tmp_path / "ledger.sqlite3")
    evaluator = JevEvaluator(store, ledger, transport=object(), origin="REAL_JEV")
    try:
        import pytest
        with pytest.raises(ValueError, match="real_evaluation_requires_real_measurements"):
            evaluator.enqueue("k1", {"candidate_id": "cand_k1_s", "lane_id": "S",
                                     "origin": "FIXTURE"}, {"origin": "FIXTURE"}, evidence_version=0)
        assert ledger.snapshot()["suites"] == 0
    finally:
        evaluator.close()
        ledger.close()
        store.close()

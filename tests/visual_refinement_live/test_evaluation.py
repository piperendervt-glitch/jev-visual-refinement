"""Transactional Q selection and first-valid-axis acceptance with synthetic vendor wire."""
import json

from src.visual_refinement_live.evaluation import SelectionEngine
from src.visual_refinement_live.jev_wire import CRITERIA
from src.visual_refinement_live.store import LiveStore
from src.visual_refinement_live import store as live_store


def _score(axis, high):
    return {"type": "score", "score": high, "confidence": 1.0,
            "legend": {str(i): CRITERIA[axis][i] for i in range(5)},
            "probabilities": {str(i): 1.0 if i == high else 0.0 for i in range(5)}}


def _raw(q, axes=("Q",)):
    return json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 300},
                       "answers": {axis: _score(axis, q if axis == "Q" else 2)
                                   for axis in axes}}).encode()


def test_q_selects_and_revises_while_retry_cannot_cherry_pick(tmp_path, monkeypatch):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "owned")
    store = LiveStore("fixture", create=True)
    store.frame("k1", {"frame_id": "k1", "pixel_sha256": "a" * 64})
    store.evidence("e_k1_0", "k1", 0, {"evidence_id": "e_k1_0", "frame_id": "k1", "version": 0})
    preview = store.put_artifact("preview_a", ".png", b"synthetic-a", "image/png")
    preview_b = store.put_artifact("preview_b", ".png", b"synthetic-b", "image/png")
    for lane, artifact in (("A", preview), ("B", preview_b)):
        store.candidate(f"cand_k1_{lane.lower()}", "k1", lane,
                        {"candidate_id": f"cand_k1_{lane.lower()}", "frame_id": "k1",
                         "lane_id": lane, "segmentation_status": "SUCCEEDED_EMPTY",
                         "mask_count": 0, "masks": [],
                         "preview_artifact_id": artifact["artifact_id"],
                         "source_pixel_sha256": "a" * 64, "origin": "FIXTURE"})
    engine = SelectionEngine(store)
    a = engine.ensure_task("k1", "cand_k1_a", "A", 0, "a" * 64, origin="FIXTURE")
    first = engine.accept_attempt(a, "a1", _raw(3), origin="FIXTURE")
    assert first["decision"]["reason_code"] == "FIRST_ELIGIBLE"
    assert first["decision"]["winner_after_id"] == "cand_k1_a"
    retry = engine.accept_attempt(a, "a2", _raw(4, ("Q", "A", "R", "I", "C")), origin="FIXTURE")
    assert retry["decision"] is None
    assert store.snapshot()["selection"]["k1"]["winner_id"] == "cand_k1_a"
    assert store.snapshot()["evaluations"][0]["axes"]["Q"]["score_decimal"] == "3"
    b = engine.ensure_task("k1", "cand_k1_b", "B", 0, "b" * 64, origin="FIXTURE")
    second = engine.accept_attempt(b, "b1", _raw(4), origin="FIXTURE")
    assert second["decision"]["reason_code"] == "HIGHER_Q"
    assert store.snapshot()["selection"]["k1"]["winner_id"] == "cand_k1_b"
    before_e1 = store.snapshot()["snapshot_seq"]
    store.evidence("e_k1_1", "k1", 1, {"evidence_id": "e_k1_1", "frame_id": "k1", "version": 1})
    assert store.snapshot()["selection"]["k1"]["winner_id"] is None
    assert store.snapshot(before_e1)["selection"]["k1"]["winner_id"] == "cand_k1_b"
    fresh = engine.ensure_task("k1", "cand_k1_b", "B", 1, "c" * 64, origin="FIXTURE")
    result = engine.accept_attempt(fresh, "b2", _raw(3), origin="FIXTURE")
    assert result["decision"]["revision_kind"] == "REFRESH_SAME"
    assert store.snapshot()["selection"]["k1"]["winner_id"] == "cand_k1_b"
    store.close()

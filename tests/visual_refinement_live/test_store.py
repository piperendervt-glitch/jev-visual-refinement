"""SC03 owned-store persistence and scope checks."""
from pathlib import Path
import sqlite3

import pytest

from src.visual_refinement_live import store as live_store


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "owned")
    return tmp_path / "owned"


def test_commit_order_replay_and_read_only(root: Path):
    run = live_store.LiveStore("test_run", create=True, source={"source_id": "approved",
                                                               "path": "private-video"})
    k = {"frame_id": "k1", "width": 2, "height": 2}
    c = {"candidate_id": "k1_s", "frame_id": "k1", "lane_id": "S", "mask_count": 0}
    kseq = run.frame("k1", k)
    cseq = run.candidate("k1_s", "k1", "S", c)
    run.close_run("COMPLETE_EMPTY")
    run.close()
    saved = live_store.LiveStore("test_run", create=False)
    early = saved.snapshot(kseq)
    assert len(early["frames"]) == 1 and early["candidates"] == []
    latest = saved.snapshot()
    assert latest["candidates"][0]["seq"] == cseq
    assert "path" not in latest["source"]
    assert latest["lifecycle"] == "SERVICE_STOPPED_NORMAL"
    with pytest.raises(ValueError, match="saved_run_read_only"):
        saved.event("ShouldNotWrite", None, None, {})
    saved.close()


def test_duplicate_candidate_rolls_back_event_and_artifact_integrity(root: Path):
    run = live_store.LiveStore("test_run", create=True)
    run.frame("k1", {"frame_id": "k1"})
    candidate = {"candidate_id": "c1", "lane_id": "S"}
    run.candidate("c1", "k1", "S", candidate)
    before = run.snapshot()["snapshot_seq"]
    with pytest.raises(sqlite3.IntegrityError):
        run.candidate("c1", "k1", "S", candidate)
    assert run.snapshot()["snapshot_seq"] == before
    meta = run.put_artifact("real_mask", ".png", b"fake-image-bytes", "image/png")
    assert run.read_artifact(meta["artifact_id"])[1] == b"fake-image-bytes"
    (run.root / "artifacts" / "real_mask.png").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="artifact_integrity"):
        run.read_artifact(meta["artifact_id"])
    run.close()


def test_visible_receipt_requires_committed_selection_source(root: Path):
    run = live_store.LiveStore("receipt_run", create=True)
    run.frame("k1", {"frame_id": "k1"})
    cseq = run.candidate("c1", "k1", "S", {"candidate_id": "c1"})
    dseq = run.decision("d1", "k1", {
        "frame_id": "k1", "candidate_id": "c1", "winner_after_id": "c1",
        "evidence_version": 0, "origin": "FIXTURE"})
    assert run.receipt(ident="r1", session_id="s1", frame_id="k1", candidate_id="c1",
                       source_seq=dseq, mode="FOLLOW_SELECTION")
    with pytest.raises(ValueError, match="receipt_selection_source_mismatch"):
        run.receipt(ident="r2", session_id="s1", frame_id="k1", candidate_id="c1",
                    source_seq=cseq, mode="FOLLOW_SELECTION")
    assert run.receipt(ident="r3", session_id="s1", frame_id="k1", candidate_id="c1",
                       source_seq=cseq, mode="MANUAL_CANDIDATE")
    run.close()

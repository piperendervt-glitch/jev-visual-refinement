"""Owned loopback HTTP serves the seven-panel saved view without mutating it."""
import json
import threading
from urllib.request import Request, urlopen

from src.visual_refinement_live import store as live_store
from src.visual_refinement_live.controller import LiveController
from src.visual_refinement_live.server import LiveServer
from src.visual_refinement_live.store import LiveStore


def test_saved_loopback_view_and_normal_shutdown(tmp_path, monkeypatch):
    monkeypatch.setattr(live_store, "RUNS_ROOT", tmp_path / "owned")
    run = LiveStore("saved", create=True, source={"source_id": "fixture", "path": "private",
                                                 "filename": "fixture.mp4"})
    run.frame("k1", {"frame_id": "k1", "actual_seconds": 0.5,
                     "requested_seconds": 0.5, "pts": 1, "time_base": [1, 2],
                     "sample_id": "sample", "pixel_sha256": "a" * 64,
                     "image_artifact_id": run.put_artifact("k", ".png", b"synthetic", "image/png")["artifact_id"]})
    candidate_seq = run.candidate("c1", "k1", "S",
                                  {"candidate_id": "c1", "frame_id": "k1", "lane_id": "S",
                                   "origin": "FIXTURE", "mask_count": 0,
                                   "segmentation_status": "SUCCEEDED_EMPTY"})
    run.close_run("COMPLETE_EMPTY")
    run.close()
    controller = LiveController(video=None, run_id="saved", lanes=("S", "A", "B", "C"),
                                open_existing=True)
    server = LiveServer(controller, ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=False)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode()
        assert html.count('class="panel ') == 7
        assert "bottom-panels" in html
        with urlopen(base + "/api/live/snapshot", timeout=3) as response:
            snapshot = json.load(response)
        assert snapshot["lifecycle"] == "SERVICE_STOPPED_NORMAL"
        assert "path" not in snapshot["source"]
        assert len(snapshot["frames"]) == 1
        with urlopen(base + "/api/live/runs/saved/snapshot", timeout=3) as response:
            replay = json.load(response)
        assert replay["run_id"] == "saved"
        assert replay["accepting"] is False
        with urlopen(base + "/api/live/runs/saved/artifacts/k", timeout=3) as response:
            assert response.read() == b"synthetic"
        before_seq = controller.snapshot()["snapshot_seq"]
        receipt = Request(base + "/api/live/view-receipts",
                          data=json.dumps({"id": "r1", "run_id": "saved",
                                           "session_id": "session1", "frame_id": "k1",
                                           "candidate_id": "c1", "source_seq": candidate_seq,
                                           "mode": "SAVED_REPLAY"}).encode(),
                          headers={"Content-Type": "application/json", "Origin": base},
                          method="POST")
        with urlopen(receipt, timeout=3) as response:
            assert json.load(response)["accepted"]
        assert controller.snapshot()["snapshot_seq"] == before_seq
        assert server.view_sessions.count("saved") == 1
        request = Request(base + "/api/live/shutdown",
                          data=b'{"action":"shutdown"}',
                          headers={"Content-Type": "application/json", "Origin": base},
                          method="POST")
        with urlopen(request, timeout=3) as response:
            assert json.load(response)["accepted"]
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        controller.close()


def test_batch_start_uses_selected_k_set_over_saved_default():
    class BatchStub:
        def __init__(self):
            self.started = None

        def k_set(self):
            return {"seconds": [0.5, 2.0]}

        def start(self, **kwargs):
            self.started = kwargs
            return {"batch_id": "fixture_transport", "plan": {"run_count": 1}}

    batch = BatchStub()
    server = LiveServer(object(), ("127.0.0.1", 0), batch_manager=batch)
    thread = threading.Thread(target=server.serve_forever, daemon=False)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(
            base + "/api/live/batch/start",
            data=json.dumps({"profiles": ["S"], "repeats": 1,
                             "k_seconds": [0.5], "bucket": "VALIDATION"}).encode(),
            headers={"Content-Type": "application/json", "Origin": base},
            method="POST")
        with urlopen(request, timeout=3) as response:
            assert response.status == 202
            assert json.load(response)["batch_id"] == "fixture_transport"
        assert batch.started == {
            "profiles": ("S",), "repeats": 1,
            "k_seconds": (0.5,), "bucket": "VALIDATION"}
    finally:
        server.shutdown()
        thread.join(timeout=5)
        assert not thread.is_alive()
        server.server_close()

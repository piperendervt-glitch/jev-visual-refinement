from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from visual_refinement_sc02 import store as store_module
from visual_refinement_sc02.media import decode_at, probe_video


class StoreMediaTest(unittest.TestCase):
    def setUp(self):
        store_module.RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=store_module.RUNS_ROOT)
        self.root = Path(self.temp.name).resolve()
        self.assertIn(store_module.RUNS_ROOT.resolve(), self.root.parents)

    def tearDown(self):
        self.assertIn(store_module.RUNS_ROOT.resolve(), self.root.parents)
        self.temp.cleanup()

    def test_store_cursor_receipt_integrity_and_capacity(self):
        run = store_module.RunStore(self.root, create=True, source={"source_id": "fixture"})
        frame_png = run.put_artifact("frame_1", ".png", b"valid-png-stand-in", "image/png")
        frame_seq = run.publish_frame("k_1", {"frame_id": "k_1", "pixel_sha256": "abc",
                                             "image_artifact_id": frame_png["artifact_id"]})
        candidate_seq = run.publish_candidate("c_1", "k_1", {"candidate_id": "c_1",
            "frame_id": "k_1", "mask_count": 0, "origin": "REAL_MODEL"})
        self.assertEqual(run.snapshot(frame_seq)["candidates"], [])
        self.assertEqual(run.snapshot(candidate_seq)["candidates"][0]["seq"], candidate_seq)
        receipt = {"id": "r1", "session_id": "v1", "frame_id": "k_1", "candidate_id": "c_1",
                   "mode": "UNSCORED_PREVIEW", "source_seq": candidate_seq}
        self.assertTrue(run.receipt(receipt))
        self.assertFalse(run.receipt(dict(receipt, id="r2")))
        with self.assertRaisesRegex(ValueError, "receipt_candidate_mismatch"):
            run.receipt(dict(receipt, id="r3", frame_id="k_other"))
        with patch.object(store_module, "MAX_OUTPUT_BYTES", len(b"valid-png-stand-in")):
            with self.assertRaisesRegex(ValueError, "output_capacity"):
                run.put_artifact("too_big", ".png", b"x", "image/png")
        run.close_run("PARTIAL_OR_EMPTY")
        run.close()
        saved = store_module.RunStore(self.root, create=False)
        self.assertEqual(saved.snapshot()["lifecycle"], "SERVICE_STOPPED_NORMAL")
        self.assertEqual(saved.read_artifact("frame_1")[1], b"valid-png-stand-in")
        with self.assertRaisesRegex(ValueError, "saved_run_read_only"):
            saved.event("Bad", None, {})
        with self.assertRaisesRegex(ValueError, "saved_run_read_only"):
            saved.receipt(dict(receipt, id="r_saved"))
        saved.close()

    def test_synthetic_h264_pts_and_pixel_identity(self):
        try:
            import av
        except ImportError:
            self.skipTest("PyAV is not installed")
        path = self.root / "synthetic.mp4"
        with av.open(str(path), "w") as output:
            stream = output.add_stream("libx264", rate=2)
            stream.width = 32
            stream.height = 24
            stream.pix_fmt = "yuv420p"
            for ordinal in range(6):
                rgb = np.zeros((24, 32, 3), dtype=np.uint8)
                rgb[:, :, ordinal % 3] = 70 + ordinal * 20
                frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)
        info = probe_video(path)
        first = decode_at(info, 0.5)
        second = decode_at(info, 1.0)
        self.assertEqual((info.codec, first.width, first.height), ("h264", 32, 24))
        self.assertGreaterEqual(first.actual_seconds, 0.5)
        self.assertGreaterEqual(second.actual_seconds, 1.0)
        self.assertNotEqual(first.sample_id, second.sample_id)
        self.assertNotEqual(first.pixel_sha256, second.pixel_sha256)
        self.assertEqual(first.rgb.shape, (24, 32, 3))

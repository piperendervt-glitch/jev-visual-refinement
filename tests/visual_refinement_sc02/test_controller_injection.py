from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from visual_refinement_sc02 import controller as module
from visual_refinement_sc02.media import Keyframe, VideoInfo
from visual_refinement_sc02.segmenter import SegmentOutput
from visual_refinement_sc02.store import RUNS_ROOT


class ControllerFailureTest(unittest.TestCase):
    def setUp(self):
        RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=RUNS_ROOT)
        self.root = Path(self.temp.name).resolve()
        self.assertIn(RUNS_ROOT.resolve(), self.root.parents)
        self.rgb = np.zeros((24, 32, 3), dtype=np.uint8)
        self.info = VideoInfo(self.root / "source.mp4", "source_test", 100, 32, 24,
                              32, 24, "h264", 0, 4.0)
        self.frame = Keyframe(0.5, 1, 1, 2, 0.5, 0, "sample_test", 32, 24,
                              self.rgb, "pixel_test")

    def tearDown(self):
        self.assertIn(RUNS_ROOT.resolve(), self.root.parents)
        self.temp.cleanup()

    def _controller(self, segmenter):
        self.addCleanup(patch.stopall)
        patch.object(module, "probe_video", return_value=self.info).start()
        patch.object(module, "decode_at", return_value=self.frame).start()
        patch.object(module, "YOLO11Segmenter", return_value=segmenter).start()
        return module.RunController(video=self.info.path, run_id=self.root.name,
                                    weight=self.root / "unused.pt")

    def test_zero_mask_is_saved_without_a_fake_candidate_score(self):
        class EmptySegmenter:
            device = "cuda:0"
            load_ms = 1.0

            def predict(self, rgb):
                return SegmentOutput(np.empty((0, 24, 32), dtype=np.uint8),
                    np.empty((0, 24, 32), dtype=np.uint8), np.empty((0, 4)),
                    np.empty((0,), dtype=np.int32), np.empty((0,)), "cuda:0",
                    {"synchronized_predict_total": 1.0})

        controller = self._controller(EmptySegmenter())
        controller.select(0.5)
        controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertEqual(view["failure"], None)
        self.assertEqual(view["job_count"], 2)
        self.assertEqual(view["candidates"][0]["segmentation_status"], "SUCCEEDED_EMPTY")
        self.assertEqual(view["candidates"][0]["evaluation"]["Q"]["score_decimal"], None)
        self.assertEqual(controller.close()["business"], "COMPLETE_EMPTY")
        saved = module.RunController(video=None, run_id=self.root.name,
                                     weight=self.root / "unused.pt", open_existing=True)
        self.assertEqual(saved.snapshot()["job_count"], 2)
        self.assertEqual(saved.snapshot()["selected_count"], 1)
        self.assertEqual(saved.close()["business"], "COMPLETE_EMPTY")

    def test_injected_oom_is_failure_not_empty_mask(self):
        class OOMSegmenter:
            device = "cuda:0"
            load_ms = 1.0

            def predict(self, rgb):
                raise RuntimeError("CUDA_OUT_OF_MEMORY_INJECTED")

        controller = self._controller(OOMSegmenter())
        controller.select(0.5)
        controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertIn("CUDA_OUT_OF_MEMORY_INJECTED", view["failure"])
        self.assertEqual(len(view["candidates"]), 0)
        self.assertIn("JobFailed", [e["kind"] for e in view["events"]])
        self.assertEqual(controller.close()["business"], "FAILED")

    def test_stop_discards_late_result(self):
        started, release = threading.Event(), threading.Event()

        class SlowSegmenter:
            device = "cuda:0"
            load_ms = 1.0
            calls = 0

            def predict(self, rgb):
                self.calls += 1
                if self.calls == 2:
                    started.set()
                    release.wait(timeout=3)
                masks = np.zeros((1, 24, 32), dtype=np.uint8)
                masks[0, 3:8, 4:10] = 1
                return SegmentOutput(masks, masks, np.array([[4, 3, 10, 8]]),
                    np.array([0]), np.array([0.8]), "cuda:0",
                    {"synchronized_predict_total": 1.0})

        controller = self._controller(SlowSegmenter())
        controller.select(0.5)
        self.assertTrue(started.wait(timeout=3))
        self.assertTrue(controller.snapshot()["worker_alive"])
        controller.stop_analysis()
        release.set()
        controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertEqual(len(view["candidates"]), 0)
        self.assertIn("JobCancelled", [e["kind"] for e in view["events"]])
        self.assertTrue(controller.close()["normal"])

    def test_reset_discards_late_result_and_allows_new_selection(self):
        started, release = threading.Event(), threading.Event()

        class SlowSegmenter:
            device = "cuda:0"
            load_ms = 1.0
            calls = 0

            def predict(self, rgb):
                self.calls += 1
                if self.calls == 2:
                    started.set()
                    release.wait(timeout=3)
                masks = np.zeros((1, 24, 32), dtype=np.uint8)
                masks[0, 3:8, 4:10] = 1
                return SegmentOutput(masks, masks, np.array([[4, 3, 10, 8]]),
                    np.array([0]), np.array([0.8]), "cuda:0",
                    {"synchronized_predict_total": 1.0})

        controller = self._controller(SlowSegmenter())
        old_id = controller.select(0.5)
        self.assertTrue(started.wait(timeout=3))
        controller.reset()
        release.set()
        controller.worker.join(timeout=3)
        self.assertEqual(controller.snapshot()["candidates"], [])
        new_id = controller.select(0.5)
        controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertNotEqual(old_id, new_id)
        self.assertEqual([c["frame_id"] for c in view["candidates"]], [new_id])
        self.assertEqual(view["selected_count"], 2)
        self.assertEqual(view["job_count"], 3)
        self.assertEqual(controller.close()["business"], "COMPLETE_NONEMPTY")
    def test_decode_failure_is_persisted_without_a_frame(self):
        controller = self._controller(object())
        with patch.object(module, "decode_at", side_effect=RuntimeError("DECODE_INJECTED")):
            controller.select(0.5)
            controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertEqual(view["frames"], [])
        self.assertEqual(view["candidates"], [])
        self.assertIn("DECODE_INJECTED", view["failure"])
        self.assertEqual(controller.close()["business"], "FAILED")

    def test_model_load_failure_is_persisted_with_original_frame(self):
        controller = self._controller(object())
        with patch.object(module, "YOLO11Segmenter", side_effect=RuntimeError("LOAD_INJECTED")):
            controller.select(0.5)
            controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertEqual(len(view["frames"]), 1)
        self.assertEqual(view["candidates"], [])
        self.assertIn("LOAD_INJECTED", view["failure"])
        self.assertEqual(controller.close()["business"], "FAILED")

    def test_inference_failure_after_warmup_counts_both_jobs(self):
        class InferenceFailure:
            device = "cuda:0"
            load_ms = 1.0
            calls = 0

            def predict(self, rgb):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("INFERENCE_INJECTED")
                masks = np.empty((0, 24, 32), dtype=np.uint8)
                return SegmentOutput(masks, masks, np.empty((0, 4)),
                    np.empty((0,), dtype=np.int32), np.empty((0,)), "cuda:0",
                    {"synchronized_predict_total": 1.0})

        controller = self._controller(InferenceFailure())
        controller.select(0.5)
        controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertEqual(view["job_count"], 2)
        self.assertEqual(view["candidates"], [])
        self.assertIn("INFERENCE_INJECTED", view["failure"])
        self.assertEqual(controller.close()["business"], "FAILED")

    def test_expired_deadline_rejects_work_without_a_gpu_job(self):
        controller = self._controller(object())
        with patch.object(module, "MAX_WALL_SECONDS", 0):
            controller.select(0.5)
            controller.worker.join(timeout=3)
        view = controller.snapshot()
        self.assertEqual(view["job_count"], 0)
        self.assertIn("run_deadline", view["failure"])
        self.assertEqual(controller.close()["business"], "FAILED")
    def test_three_selected_keyframes_is_a_hard_limit(self):
        class EmptySegmenter:
            device = "cuda:0"
            load_ms = 1.0

            def predict(self, rgb):
                masks = np.empty((0, 24, 32), dtype=np.uint8)
                return SegmentOutput(masks, masks, np.empty((0, 4)),
                    np.empty((0,), dtype=np.int32), np.empty((0,)), "cuda:0",
                    {"synchronized_predict_total": 1.0})

        controller = self._controller(EmptySegmenter())
        for _ in range(3):
            controller.select(0.5)
            controller.worker.join(timeout=3)
        with self.assertRaisesRegex(ValueError, "keyframe_limit"):
            controller.select(0.5)
        view = controller.snapshot()
        self.assertEqual(view["selected_count"], 3)
        self.assertEqual(view["job_count"], 4)
        self.assertEqual(controller.close()["business"], "COMPLETE_EMPTY")
from pathlib import Path
import tempfile
import unittest

from visual_refinement_sc01.repair import (
    FixtureKernel, FixtureProfile, prepare_live_demo, publish_demo_evidence,
    release_demo_step,
)


class SC05AProjectionTests(unittest.TestCase):
    def test_lane_queue_and_congestion_then_saturation_are_real_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kernel = FixtureKernel(root / "state.sqlite3", root / "artifacts",
                                   profile=FixtureProfile(queue_capacity=4))
            try:
                prepare_live_demo(kernel)
                view = kernel.view("frame_k0")
                queue = view["queues"][0]
                self.assertEqual((queue["queued"], queue["capacity"], queue["congestion"]),
                                 (3, 4, "CONGESTED"))
                self.assertEqual(queue["stage"], "EVALUATION")
                self.assertEqual(queue["unit"], "EVALUATION_SUITE")
                self.assertEqual([r["queue"]["queued"] for r in view["rows"]], [1, 1, 1, 0])

                publish_demo_evidence(kernel)
                view = kernel.view("frame_k0")
                queue = view["queues"][0]
                self.assertEqual((queue["queued"], queue["congestion"]), (4, "SATURATED"))
                self.assertEqual(sum(r["queue"]["queued"] for r in view["rows"]), queue["queued"])
                self.assertEqual(queue["rejected_total"], 2)
                kernel.close_run()
            finally:
                kernel.close()

            reopened = FixtureKernel(root / "state.sqlite3", root / "artifacts", create=False)
            try:
                saved = reopened.view("frame_k0")
                self.assertEqual(saved["run_status"], "CLOSED_PARTIAL")
                self.assertEqual((saved["queues"][0]["capacity"], saved["queues"][0]["queued"]), (4, 4))
            finally:
                reopened.close()

    def test_zero_wait_is_not_zero_age(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kernel = FixtureKernel(root / "state.sqlite3", root / "artifacts")
            try:
                prepare_live_demo(kernel)
                for _ in range(3):
                    release_demo_step(kernel)
                queue = kernel.view("frame_k0")["queues"][0]
                self.assertEqual(queue["queued"], 0)
                self.assertEqual(queue["congestion"], "NORMAL")
                self.assertIsNone(queue["oldest_queued_ms"])
            finally:
                kernel.close()

    def test_flow_pulses_are_bounded_and_tied_to_recorded_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kernel = FixtureKernel(root / "state.sqlite3", root / "artifacts")
            try:
                prepare_live_demo(kernel)
                before = kernel.view("frame_k0")["flow_pulses"]
                self.assertEqual(len(before), 4)  # one actual candidate-publication transition per lane
                self.assertEqual(before, kernel.view("frame_k0")["flow_pulses"])
                release_demo_step(kernel)
                after = kernel.view("frame_k0")["flow_pulses"]
                event_ids = {e["event_id"] for e in kernel.event_page()["events"]}
                self.assertTrue(all(p["event_id"] in event_ids for p in after))
                self.assertTrue(all(p["duration_ms"] == 500 and p["origin"] == "FIXTURE" for p in after))
                self.assertEqual(len({p["pulse_id"] for p in after}), len(after))
                self.assertTrue(any(p["phase"] == "EvaluationAttemptFinished" for p in after))
            finally:
                kernel.close()


if __name__ == "__main__":
    unittest.main()

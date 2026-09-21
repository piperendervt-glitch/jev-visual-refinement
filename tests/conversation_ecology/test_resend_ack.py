"""C0 resend regressions. Any browser_dom record here is an isolated unit contract,
never a real browser observation; live HTTP checks below do not send browser acks.
"""
import copy
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from conversation_ecology.server import App, make_server


class ResendContracts(unittest.TestCase):
    def test_no_commit_records_no_target(self):
        app = App()
        state = app.action({"action": "resend", "session_id": "fixture-0"})
        self.assertEqual(state["operation"]["result"], "no_commits")
        self.assertEqual(state["operation"]["commit_ids"], [])
        self.assertEqual([e["kind"] for e in state["events"]], ["resend"])
        self.assertFalse(state["commits"] or state["acks"])

    def test_unacked_commit_repeated_delivery_and_replay(self):
        app = App()
        before = app.action({"action": "demo", "name": "short"})
        for index in range(3):
            state = app.action({"action": "resend", "session_id": before["session_id"]})
            self.assertEqual(state["commits"], before["commits"])
            self.assertFalse(state["acks"])
            self.assertEqual(state["operation"]["commit_ids"], [before["commits"][0]["id"]])
            self.assertEqual(len([e for e in state["events"] if e["kind"] == "delivery"]), 1)
            self.assertEqual(len([e for e in state["events"] if e["kind"] == "resend"]), index+1)
        self.assertEqual(app.engine.projection()["resends"], [e["payload"] for e in state["events"] if e["kind"] == "resend"])

    def test_browser_ack_contract_in_memory_only(self):
        # Explicit unit-only contract fixture, not a real rendering acknowledgement.
        app = App()
        before = app.action({"action": "demo", "name": "short"})
        cid = before["commits"][0]["id"]
        self.assertTrue(app.engine.acknowledge(cid, "connected_dom_after_two_animation_frames", kind="browser_dom"))
        before = copy.deepcopy(app.engine.view())
        for _ in range(3):
            state = app.action({"action": "resend"})
            self.assertEqual(state["operation"]["result"], "resent")
            self.assertEqual(state["operation"]["browser_acked_commit_ids"], [cid])
            self.assertEqual(state["commits"], before["commits"])
            self.assertEqual(state["acks"], before["acks"])
        self.assertFalse(app.engine.acknowledge(cid, "connected_dom_after_two_animation_frames", kind="browser_dom"))

    def test_synthetic_ack_is_not_counted_as_browser_ack(self):
        app = App()
        state = app.action({"action": "demo", "name": "short"})
        app.engine.acknowledge(state["commits"][0]["id"], "unit-test-only")
        state = app.action({"action": "resend"})
        self.assertEqual(state["operation"]["browser_acked_commit_ids"], [])
        self.assertEqual(state["acks"][0]["kind"], "synthetic_test")

    def test_old_session_resend_and_ack_rejected_without_mutation(self):
        app = App()
        old = app.action({"action": "demo", "name": "short"})
        app.action({"action": "demo", "name": "correction"})
        before = copy.deepcopy(app.engine.view())
        for action in ("resend", "ack"):
            with self.assertRaisesRegex(ValueError, "stale_session"):
                app.action({"action": action, "session_id": old["session_id"],
                            "commit_id": old["commits"][0]["id"],
                            "evidence": "connected_dom_after_two_animation_frames"})
            self.assertEqual(app.engine.view(), before)
        with self.assertRaisesRegex(ValueError, "unknown_or_unsent_commit"):
            app.action({"action": "ack", "commit_id": old["commits"][0]["id"],
                        "evidence": "connected_dom_after_two_animation_frames"})

    def test_old_revision_is_history_not_new_answer(self):
        app = App()
        old = app.action({"action": "demo", "name": "short"})
        app.action({"action": "utterance", "text": "corrected fixture greeting", "revision": True})
        state = app.action({"action": "resend", "session_id": old["session_id"]})
        self.assertEqual(state["commits"], old["commits"])
        self.assertNotEqual(state["commits"][0]["snapshot_id"], state["snapshot"]["snapshot_id"])
        self.assertEqual(state["snapshot"]["utterance_revision"], 2)
        self.assertTrue(any(e["kind"] == "correction" for e in state["events"]))
        self.assertFalse(state["acks"])


class ResendHttp(unittest.TestCase):
    def test_loopback_response_and_rejection(self):
        server = make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def call(command=None, authorized=True):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                headers = {"Origin": f"http://127.0.0.1:{server.server_port}"}
                if authorized: headers["X-C0-Token"] = server.app.token
                conn.request("GET" if command is None else "POST",
                             "/api/state" if command is None else "/api/action",
                             body=None if command is None else json.dumps(command), headers=headers)
                response = conn.getresponse()
                result = response.status, json.loads(response.read())
                conn.close()
                return result
            _, before = call({"action": "demo", "name": "short"})
            status, state = call({"action": "resend", "session_id": before["session_id"]})
            self.assertEqual(status, 200)
            self.assertEqual(state["commits"], before["commits"])
            self.assertEqual(state["operation"]["semantics"], "response_prepared_not_browser_receipt")
            self.assertEqual(state["events"][-1]["id"], state["operation"]["event_id"])
            self.assertFalse(state["acks"])
            count = len(state["events"])
            self.assertEqual(call({"action": "resend"}, authorized=False)[0], 403)
            self.assertEqual(call({"action": "resend", "session_id": "old-session"})[0], 400)
            self.assertEqual(len(call()[1]["events"]), count)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()

"""メモリ内の合成journalと、通信しない記録投影Replay。"""
import copy


def replay(events):
    state = {"snapshots": [], "candidates": [], "evaluations": [], "decisions": [],
             "commits": [], "deliveries": [], "resends": [], "acks": [], "threads": {}, "fixture_evaluation_attempts": 0}
    mapping = {"snapshot": "snapshots", "candidates": "candidates", "evaluation": "evaluations",
               "decision": "decisions", "commit": "commits", "delivery": "deliveries", "resend": "resends", "ack": "acks"}
    for seq, event in enumerate(events, 1):
        if event["cursor"] != seq or event["mode"] != "FIXTURE": raise ValueError("replay_order_or_mode")
        kind, payload = event["kind"], copy.deepcopy(event["payload"])
        if kind in mapping: state[mapping[kind]].append(payload)
        if kind == "thread": state["threads"][payload["snapshot_id"]] = payload["state"]
        if kind == "evaluation": state["fixture_evaluation_attempts"] += 1
    return state

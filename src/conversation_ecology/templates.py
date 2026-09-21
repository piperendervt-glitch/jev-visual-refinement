"""6系列は同じsnapshotを参照する。候補名は採用規則に使わない。"""
from dataclasses import replace
import hashlib
import json
from .contracts import Candidate


def greeting(s):
    if any(word in s.text for word in ("こんにちは", "こんばんは", "おはよう")):
        return [("こんにちは。", "greeting", "acknowledgement", ())]
    return []


def listening(s):
    return [("お話を聞いています。", "listening", "backchannel", ())]


def encouragement(s):
    if any(word in s.text for word in ("相談", "困", "不安")):
        return [("少しずつ聞かせてください。", "encouragement", "acknowledgement", ())]
    return []


def thanks(s):
    if "ありがとう" in s.text:
        return [("伝えてくれて、ありがとうございます。", "thanks", "final_micro", ())]
    return []


def work_status(s):
    if s.work_states:
        return [("合成作業は承認待ちです。実作業は開始していません。", "work_status", "acknowledgement", ("simulated_work",))]
    return []


def silence(s):
    return [("", "silence", "silence", ()), ("", "defer_to_main", "silence", ("main_pending",))]


GENERATORS = (("Greeting", greeting), ("Listening", listening),
              ("Encouragement", encouragement), ("Thanks", thanks),
              ("WorkStatus", work_status), ("Silence", silence))


def deduplicate(candidates):
    unique = {}
    for c in candidates:
        key = (c.snapshot_id, c.turn_id, c.revision, c.text, c.act, c.slot, c.prerequisites, c.eligible)
        if key in unique:
            unique[key] = replace(unique[key], proposers=tuple(sorted(set(unique[key].proposers + c.proposers))))
        else:
            unique[key] = c
    return list(unique.values())


def generate(snapshot, main_pending=False):
    proposals, calls = [], []
    for name, generator in GENERATORS:
        rows = generator(snapshot)
        calls.append({"generator": name, "snapshot_id": snapshot.snapshot_id, "count": len(rows),
                      "reason": "proposed" if rows else "precondition_not_met"})
        for text, act, slot, pre in rows:
            key = json.dumps([snapshot.snapshot_id, text, act, slot, pre], ensure_ascii=False)
            identity = "candidate-" + hashlib.sha256(key.encode()).hexdigest()[:16]
            eligible = snapshot.source == "user_fixture" and ("main_pending" not in pre or main_pending)
            proposals.append(Candidate(identity, snapshot.snapshot_id, snapshot.turn_id,
                                        snapshot.utterance_revision, text, act, slot, pre, (name,), eligible))
    candidates = deduplicate(proposals)
    return candidates[:8], calls, {"before": len(proposals), "after": len(candidates[:8]),
                                  "deferred": max(0, len(candidates)-8)}

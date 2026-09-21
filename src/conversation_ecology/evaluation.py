"""アプリのfixture契約。vendor SDK応答・実Jev性能の再現ではない。"""
from .contracts import number

AXES = ("task_fit", "context_fit", "timing_fit")


class FixtureEvaluator:
    def evaluate(self, snapshot, candidates, profile="balanced", overrides=None):
        if profile not in {"balanced", "low", "missing", "timeout"}:
            raise ValueError("unknown_fixture_profile")
        overrides = overrides or {}
        if not set(overrides) <= {c.id for c in candidates}:
            raise ValueError("unknown_candidate_override")
        rows = {}
        for c in candidates:
            # Semantic fixture values are independent of tests' expected winner.
            score = 3.2
            if c.act == "greeting": score = 3.8
            if c.act == "thanks": score = 3.9
            if c.act == "work_status": score = 3.7
            if c.act == "silence": score = 2.4
            if c.act == "defer_to_main": score = 2.6
            if profile == "low": score = 1.0
            rows[c.id] = dict.fromkeys(AXES, score)
        rows.update(overrides)
        if profile == "missing": rows = {}
        return {"mode": "FIXTURE", "rubric_version": "micro-c0-v1", "snapshot_id": snapshot.snapshot_id,
                "revision": snapshot.utterance_revision, "status": "TIMEOUT" if profile == "timeout" else "COMPLETED",
                "candidate_ids": [c.id for c in candidates], "scores": rows}


def validate(payload, snapshot, candidates):
    if not isinstance(payload, dict): raise ValueError("evaluation_shape")
    if payload.get("mode") != "FIXTURE" or payload.get("rubric_version") != "micro-c0-v1":
        raise ValueError("evaluation_contract")
    if payload.get("snapshot_id") != snapshot.snapshot_id or payload.get("revision") != snapshot.utterance_revision:
        raise ValueError("evaluation_binding")
    ids = [c.id for c in candidates]
    if payload.get("candidate_ids") != ids: raise ValueError("candidate_set")
    if payload.get("status") == "TIMEOUT": return "TIMEOUT", {}
    if payload.get("status") != "COMPLETED": raise ValueError("evaluation_status")
    rows = payload.get("scores")
    if not isinstance(rows, dict) or set(rows) != set(ids): raise ValueError("missing_scores")
    result = {}
    for cid, axes in rows.items():
        if not isinstance(axes, dict) or set(axes) != set(AXES): raise ValueError("axes")
        normalized = {k: number(v, 0, 4)/4 for k, v in axes.items()}
        q = .45*normalized["task_fit"] + .35*normalized["context_fit"] + .20*normalized["timing_fit"]
        result[cid] = {"raw": dict(axes), "normalized": normalized, "Q": q,
                       "probability": None, "confidence": None}
    return "VALID", result


def audit_value(value):
    """不正数値もJSON journalに安全に残す。評価値へは再解釈しない。"""
    import math
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_numeric_text": repr(value)}
    if isinstance(value, dict): return {k: audit_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [audit_value(v) for v in value]
    return value

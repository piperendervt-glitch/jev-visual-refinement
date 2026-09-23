"""Saved policy replay distinguishes arrival order and evidence context."""
from src.visual_refinement_live.analysis import _policy_comparison


def test_saved_counterfactual_uses_first_q_and_full_wait_without_e0_e1_mixing():
    view = {
        "evaluations": [
            {"frame_id": "k1", "evidence_version": 0, "candidate_id": "a",
             "seq": 1, "axes": {"Q": {"status": "VALID", "score_decimal": "3.1", "seq": 10}}},
            {"frame_id": "k1", "evidence_version": 0, "candidate_id": "b",
             "seq": 2, "axes": {"Q": {"status": "VALID", "score_decimal": "3.8", "seq": 20}}},
            {"frame_id": "k1", "evidence_version": 1, "candidate_id": "a",
             "seq": 3, "axes": {"Q": {"status": "VALID", "score_decimal": "3.3", "seq": 30}}},
        ],
        "events": [{"seq": x, "at_ms": x * 100, "kind": "EvaluationAttemptFinished"}
                   for x in (10, 20, 30)],
    }
    result = _policy_comparison(view)
    assert len(result) == 2
    assert result[0]["first_eligible_id"] == "a"
    assert result[0]["full_wait_winner_id"] == "b"
    assert result[0]["first_eligible_at_ms"] == 1000
    assert result[0]["full_wait_at_ms"] == 2000
    assert result[1]["evidence_version"] == 1
    assert result[1]["full_wait_winner_id"] == "a"
    assert all(x["saved_counterfactual"] for x in result)

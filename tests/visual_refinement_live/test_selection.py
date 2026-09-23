"""Q adoption, tie, non-Q diagnostics, and E1 invalidation."""
from src.visual_refinement_live.selection import SelectionState, decide, update_evidence


def test_q_arrival_order_and_evidence_revision():
    state = SelectionState("k1")
    state, first = decide(state, candidate_id="a", evidence_version=0,
                          q_status="VALID", q_decimal="3.1", available=True)
    assert first.reason_code == "FIRST_ELIGIBLE" and state.winner_id == "a"
    state, lower = decide(state, candidate_id="b", evidence_version=0,
                          q_status="VALID", q_decimal="3.0", available=True)
    assert lower.reason_code == "LOWER_Q" and lower.winner_after_id == "a"
    state, higher = decide(state, candidate_id="c", evidence_version=0,
                           q_status="VALID", q_decimal="3.8", available=True)
    assert higher.revision_kind == "REPLACE" and state.winner_id == "c"
    state, tie = decide(state, candidate_id="d", evidence_version=0,
                        q_status="VALID", q_decimal="3.8", available=True)
    assert tie.reason_code == "TIE_KEEP_CURRENT" and state.winner_id == "c"
    state = update_evidence(state, 1)
    assert state.winner_id is None and state.stale_fallback_id == "c"
    unchanged, old = decide(state, candidate_id="c", evidence_version=0,
                            q_status="VALID", q_decimal="4.0", available=True)
    assert old.reason_code == "OLD_EVIDENCE" and unchanged == state
    state, fresh = decide(state, candidate_id="c", evidence_version=1,
                          q_status="VALID", q_decimal="3.4", available=True)
    assert fresh.revision_kind == "REFRESH_SAME" and state.winner_id == "c"


def test_missing_and_below_threshold_never_become_zero_score():
    state = SelectionState("k1")
    for status, value, reason in (("MISSING", None, "Q_UNAVAILABLE"),
                                  ("INVALID", None, "Q_UNAVAILABLE"),
                                  ("VALID", "0", "BELOW_Q_THRESHOLD")):
        next_state, result = decide(state, candidate_id="a", evidence_version=0,
                                    q_status=status, q_decimal=value, available=True)
        assert next_state.winner_id is None
        assert result.reason_code == reason
        assert result.candidate_q is None if status != "VALID" else result.candidate_q == "0"

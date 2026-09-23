"""Persistent budget reservation, including unknown delivery after timeout."""
import pytest

from src.visual_refinement_live.ledger import BudgetLedger, RESERVED_MICRO_USD


def test_reservations_survive_restart_and_timeout_is_not_refunded(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = BudgetLedger(path)
    ledger.reserve_suite(run_id="r1", frame_id="k1", lane_id="S", evidence_version=0)
    ledger.reserve_http_attempt(attempt_id="a1", run_id="r1", frame_id="k1",
                                lane_id="S", body_bytes=1000, questions=5)
    ledger.mark_attempt("a1", "TIMEOUT_UNKNOWN")
    assert ledger.snapshot()["reserved_micro_usd"] == RESERVED_MICRO_USD
    ledger.close()
    restored = BudgetLedger(path)
    assert restored.snapshot()["suites"] == 1
    assert restored.snapshot()["http_attempts"] == 1
    assert restored.snapshot()["questions"] == 5
    restored.reserve_http_attempt(attempt_id="a1", run_id="r1", frame_id="k1",
                                  lane_id="S", body_bytes=1000, questions=5)
    assert restored.snapshot()["http_attempts"] == 1
    with pytest.raises(ValueError, match="http_budget"):
        restored.reserve_http_attempt(attempt_id="oversize", run_id="r1", frame_id="k1",
                                      lane_id="S", body_bytes=32769, questions=5)
    restored.close()

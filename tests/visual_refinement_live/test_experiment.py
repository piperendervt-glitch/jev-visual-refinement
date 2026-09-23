"""SC06 fixed experiment capacity arithmetic."""
import pytest

from src.visual_refinement_live.experiment import define_experiment, estimate


def test_six_run_plan_counts_actual_pairwise_e1_scope():
    plan = estimate(define_experiment())
    assert plan["run_count"] == 6
    assert plan["segmentation_jobs"] == 32
    assert plan["e0_suites"] == 32
    assert plan["e1_suites"] == 28
    assert plan["logical_suites"] == 60
    assert plan["max_http_attempts"] == 120
    assert plan["max_questions"] == 600
    assert plan["limitation"].startswith("ONLY_TWO")


def test_profiles_and_k_are_closed_sets():
    with pytest.raises(ValueError, match="profile_outside_fixed_set"):
        define_experiment(profiles=("S", "UNKNOWN"))
    with pytest.raises(ValueError, match="k_outside_approved_collection"):
        define_experiment(k_seconds=(0.5, 4.0))

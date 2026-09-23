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


def test_all_run_denominator_keeps_partial_runs_in_condition_group(tmp_path, monkeypatch):
    from dataclasses import asdict

    from src.visual_refinement_live import analysis as analysis_module
    from src.visual_refinement_live import store as store_module
    from src.visual_refinement_live.analysis import analysis_snapshot, compare_runs
    from src.visual_refinement_live.evaluation import SelectionEngine
    from src.visual_refinement_live.experiment import define_experiment
    from src.visual_refinement_live.store import LiveStore
    from test_jev_client import _raw

    owned = tmp_path / "owned"
    monkeypatch.setattr(store_module, "RUNS_ROOT", owned)
    monkeypatch.setattr(analysis_module, "RUNS_ROOT", owned)
    keyframe = {"requested_seconds": 0.5, "pts": 500, "time_base": [1, 1000],
                "pixel_sha256": "a" * 64, "sample_id": "synthetic",
                "width": 16, "height": 16}
    definition = define_experiment(profiles=("S",), repeats=1,
                                   k_seconds=(0.5,), k_manifest=(keyframe,))
    experiment = {"origin": "REAL", "jev": True, "profile": "S",
                  "definition": asdict(definition),
                  "definition_digest": definition.digest,
                  "planned_k_seconds": [0.5]}

    def saved_run(ident, *, e0, business, pts=500):
        run = LiveStore(ident, create=True, source={"source_id": "synthetic-source"},
                        experiment=experiment)
        run.frame("k1", dict(keyframe, frame_id="k1", pts=pts))
        run.evidence("e1", "k1", 0, {"frame_id": "k1", "version": 0})
        preview = run.put_artifact("preview", ".png", b"synthetic", "image/png")
        run.candidate("c1", "k1", "S", {"candidate_id": "c1", "frame_id": "k1",
                                              "lane_id": "S", "origin": "REAL_MODEL",
                                              "segmentation_status": "SUCCEEDED_EMPTY",
                                              "mask_count": 0, "masks": [],
                                              "preview_artifact_id": preview["artifact_id"],
                                              "source_pixel_sha256": "a" * 64})
        if e0:
            engine = SelectionEngine(run)
            task_id = engine.ensure_task("k1", "c1", "S", 0, "synthetic-digest",
                                         origin="REAL_JEV")
            engine.accept_attempt(task_id, "attempt1", _raw(), origin="REAL_JEV")
        run.close_run(business)
        run.close()

    saved_run("complete", e0=True, business="COMPLETE_EMPTY")
    saved_run("missing_e0", e0=False, business="COMPLETE_EMPTY")
    saved_run("failed", e0=True, business="PARTIAL_FAILURE")
    saved_run("wrong_k", e0=True, business="COMPLETE_EMPTY", pts=501)
    index = analysis_snapshot(owned)
    assert index["all_target_run_count"] == 4
    assert index["excluded"] == [{"run_id": "wrong_k",
                                  "reason": "INPUT_FINGERPRINT_MISMATCH"}]
    assert {x["run_id"]: x["reason"] for x in index["incomplete"]} == {
        "missing_e0": "LANE_OR_EVALUATION_INCOMPLETE", "failed": "RUN_NOT_COMPLETE"}
    assert [group["run_ids"] for group in index["comparable_groups"]] == [
        ["complete", "failed", "missing_e0"]]
    comparison = compare_runs(owned)
    assert len(comparison["actual_configuration_comparison"]) == 1
    actual = comparison["actual_configuration_comparison"][0]
    assert actual["run_count"] == 3
    assert actual["complete_run_count"] == 1
    assert actual["incomplete_run_count"] == 2

"""Read-only all-run index and three distinct comparisons."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
from statistics import median

from .experiment import PROFILES
from .store import LiveStore, RUNS_ROOT, SCHEMA

INDEX_VERSION = "analysis-snapshot-v1"
FIXED_RULE_VERSION = "largest-union-coverage-v1"


def _run_summary(snapshot: dict) -> dict:
    frames = snapshot["frames"]
    candidates = snapshot["candidates"]
    evaluations = snapshot["evaluations"]
    decisions = snapshot["decisions"]
    jobs = snapshot["jobs"]
    experiment = snapshot["experiment"] or {}
    selected = {fid: entry["winner_id"] for fid, entry in snapshot["selection"].items()}
    profile = experiment.get("profile")
    expected_lanes = set(PROFILES.get(profile, ()))
    frame_complete = bool(expected_lanes) and all(
        len([c for c in candidates if c["frame_id"] == frame["frame_id"]])
        == len(expected_lanes) and
        {c["lane_id"] for c in candidates if c["frame_id"] == frame["frame_id"]
         and c.get("segmentation_status") in {"SUCCEEDED_NONEMPTY", "SUCCEEDED_EMPTY"}}
        == expected_lanes and
        all(
            {e["candidate_id"] for e in evaluations
             if e["frame_id"] == frame["frame_id"] and e["evidence_version"] == version
             and e.get("origin") == "REAL_JEV" and e.get("status") == "COMPLETE"}
            == {c["candidate_id"] for c in candidates
                if c["frame_id"] == frame["frame_id"]}
            for version in ((0, 1) if len(expected_lanes) > 1 else (0,))
        )
        for frame in frames
    )
    first = {}
    for d in decisions:
        fid = d["frame_id"]
        if d.get("winner_after_id") and fid not in first:
            first[fid] = {"candidate_id": d["winner_after_id"],
                          "seq": d["seq"], "evidence_version": d["evidence_version"]}
    terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}
    event_by_seq = {e["seq"]: e for e in snapshot["events"]}
    request_ms = {e["frame_id"]: e["at_ms"] for e in snapshot["events"]
                  if e["kind"] == "KeyframeRequested"}
    first_mask_ms = {}
    for e in snapshot["events"]:
        if e["kind"] == "CandidatePublished" and e["frame_id"] not in first_mask_ms:
            first_mask_ms[e["frame_id"]] = e["at_ms"]
    frame_latency = []
    for frame in frames:
        fid = frame["frame_id"]
        requested = request_ms.get(fid)
        adopted = event_by_seq.get(first.get(fid, {}).get("seq"))
        frame_latency.append({
            "frame_id": fid,
            "first_mask_ms": max(0, first_mask_ms[fid] - requested)
            if requested is not None and fid in first_mask_ms else None,
            "first_adoption_ms": max(0, adopted["at_ms"] - requested)
            if requested is not None and adopted is not None else None})
    peaks = [e["payload"].get("gpu_peak_allocated_bytes")
             for e in snapshot["events"] if e["kind"] == "InferenceFinished"]
    peaks = [x for x in peaks if isinstance(x, int)]
    return {
        "run_id": snapshot["run_id"], "schema": snapshot["schema"],
        "lifecycle": snapshot["lifecycle"], "business": snapshot["business"],
        "origin": ("REAL" if experiment.get("jev") and
                   all(c.get("origin") == "REAL_MODEL" for c in candidates) else
                   "FIXTURE" if any(c.get("origin") == "FIXTURE" for c in candidates) else
                   "JEV_OFF_OR_UNEXECUTED"),
        "experiment": experiment, "source_id": snapshot["source"].get("source_id"),
        "frame_signature": [
            {"requested_seconds": f["requested_seconds"], "pts": f["pts"],
             "time_base": f["time_base"], "pixel_sha256": f["pixel_sha256"]}
            for f in frames],
        "frames": len(frames), "candidate_count": len(candidates),
        "frame_complete": frame_complete,
        "empty_count": sum(c.get("segmentation_status") == "SUCCEEDED_EMPTY" for c in candidates),
        "e0_evaluations": sum(e["evidence_version"] == 0 for e in evaluations),
        "e1_evaluations": sum(e["evidence_version"] == 1 for e in evaluations),
        "valid_q": sum(e["axes"].get("Q", {}).get("status") == "VALID" for e in evaluations),
        "first_adoptions": first, "final_selection": selected,
        "frame_latency": frame_latency,
        "peak_gpu_allocated_bytes": max(peaks, default=None),
        "revision_count": len(snapshot["revisions"]),
        "job_counts": {status: sum(j["status"] == status for j in jobs)
                       for status in ("QUEUED", "RUNNING", "SUCCEEDED",
                                      "FAILED", "CANCELLED", "EXPIRED")},
        "terminal_jobs": sum(j["status"] in terminal for j in jobs),
        "attempts": len(snapshot["eval_attempts"]),
        "recorded_input_tokens": sum(a["input_tokens"] or 0 for a in snapshot["eval_attempts"]),
        "missing_usage_attempts": sum(a["input_tokens"] is None for a in snapshot["eval_attempts"]),
        "segmentation_duration_ms": sum(
            max(0, (j["finished_ms"] or 0) - (j["started_ms"] or 0))
            for j in jobs if j["stage"] == "SEGMENTATION" and j["started_ms"] and j["finished_ms"]),
    }


def analysis_snapshot(root: Path = RUNS_ROOT) -> dict:
    """Every owned live-schema run is indexed, including partial and failed runs."""
    entries = []
    for path in sorted(root.iterdir()) if root.is_dir() else ():
        if path.is_symlink() or not path.is_dir() or not (path / "state.sqlite3").is_file():
            continue
        try:
            store = LiveStore(path.name, create=False)
            try:
                view = store.snapshot()
            finally:
                store.close()
            entries.append(_run_summary(view))
        except (ValueError, OSError, KeyError, json.JSONDecodeError, sqlite3.Error) as exc:
            entries.append({"run_id": path.name, "status": "UNREADABLE",
                            "reason": type(exc).__name__})
    comparable = defaultdict(list)
    excluded = []
    incomplete = []
    for entry in entries:
        exp = entry.get("experiment") or {}
        definition = exp.get("definition") or {}
        planned = definition.get("k_manifest") or []
        observed = entry.get("frame_signature") or []
        planned_signatures = [
            {key: source.get(key) for key in
             ("requested_seconds", "pts", "time_base", "pixel_sha256")}
            for source in planned if isinstance(source, dict)]
        planned_by_second = {item["requested_seconds"]: item for item in planned_signatures}
        if entry.get("schema") != SCHEMA:
            reason = "SCHEMA"
        elif entry.get("origin") != "REAL" or not exp.get("definition_digest"):
            reason = "ORIGIN_OR_DEFINITION"
        elif (not planned or len(planned_signatures) != len(planned) or
              len(planned_by_second) != len(planned_signatures) or
              list(planned_by_second) != exp.get("planned_k_seconds") or
              entry.get("source_id") is None):
            reason = "PLAN_OR_SOURCE_MISSING"
        elif (len(observed) > len(planned) or
              len({item.get("requested_seconds") for item in observed}) != len(observed) or
              any(item != planned_by_second.get(item.get("requested_seconds"))
                  for item in observed)):
            reason = "INPUT_FINGERPRINT_MISMATCH"
        else:
            reason = None
        if reason:
            excluded.append({"run_id": entry["run_id"], "reason": reason})
            continue
        completion_reason = (
            "RUN_NOT_COMPLETE" if entry.get("lifecycle") != "SERVICE_STOPPED_NORMAL" or
            entry.get("business") not in {"COMPLETE_NONEMPTY", "COMPLETE_EMPTY"} else
            "MISSING_KEYFRAME" if len(observed) != len(planned) else
            "LANE_OR_EVALUATION_INCOMPLETE" if not entry.get("frame_complete") else None)
        entry["comparison_complete"] = completion_reason is None
        if completion_reason:
            incomplete.append({"run_id": entry["run_id"], "reason": completion_reason})
        common = {
            "task": exp.get("definition", {}).get("task"),
            "source_id": entry["source_id"],
            "frames": planned_signatures,
            "definition_digest": exp["definition_digest"],
            "measurement_profile": exp.get("definition", {}).get("measurement_profile"),
            "rubric_version": exp.get("definition", {}).get("rubric_version"),
            "selection_policy": exp.get("definition", {}).get("selection_policy"),
            "jev_model": exp.get("definition", {}).get("jev_model"),
            "precision": exp.get("definition", {}).get("precision"),
            "confidence": exp.get("definition", {}).get("confidence"),
            "max_instances": exp.get("definition", {}).get("max_instances"),
        }
        key = sha256(json.dumps(common, sort_keys=True).encode()).hexdigest()
        comparable[key].append(entry["run_id"])
    return {"version": INDEX_VERSION, "runs": entries,
            "comparable_groups": [{"key": key, "run_ids": ids}
                                  for key, ids in comparable.items()],
            "excluded": excluded, "incomplete": incomplete,
            "all_target_run_count": len(entries)}


def _policy_comparison(view: dict) -> list[dict]:
    """Use recorded Q arrivals; full-wait is a saved counterfactual."""
    output = []
    by_frame_version = defaultdict(list)
    for evaluation in view["evaluations"]:
        q = evaluation["axes"].get("Q")
        if q and q.get("status") == "VALID":
            by_frame_version[(evaluation["frame_id"], evaluation["evidence_version"])].append(
                (q.get("seq", evaluation["seq"]), evaluation["candidate_id"],
                 Decimal(str(q["score_decimal"]))))
    event_times = {e["seq"]: e["at_ms"] for e in view["events"]}
    for (frame_id, version), arrivals in sorted(by_frame_version.items()):
        ordered = sorted(arrivals)
        eligible = [x for x in ordered if x[2] >= 3]
        final = max(eligible, key=lambda x: x[2]) if eligible else None
        first = eligible[0] if eligible else None
        output.append({"frame_id": frame_id, "evidence_version": version,
                       "saved_counterfactual": True,
                       "first_eligible_id": first[1] if first else None,
                       "full_wait_winner_id": final[1] if final else None,
                       "first_eligible_seq": first[0] if first else None,
                       "full_wait_seq": ordered[-1][0] if ordered else None,
                       "first_eligible_at_ms": event_times.get(first[0]) if first else None,
                       "full_wait_at_ms": event_times.get(ordered[-1][0]) if ordered else None,
                       "quality_ground_truth": None})
    return output


def _fixed_evaluator(view: dict) -> list[dict]:
    """Explicit fixed geometry heuristic on the same committed local inputs."""
    result = []
    measures = {m.get("candidate_id"): m for m in view["measurements"]
                if m.get("kind") == "INITIAL"}
    for frame in view["frames"]:
        options = []
        for candidate in view["candidates"]:
            if candidate["frame_id"] != frame["frame_id"]:
                continue
            m = measures.get(candidate["candidate_id"])
            if m and m.get("union_coverage_fraction") is not None:
                options.append((m["union_coverage_fraction"], candidate["candidate_id"]))
        winner = max(options, default=None)
        result.append({"frame_id": frame["frame_id"], "fixed_rule": FIXED_RULE_VERSION,
                       "fixed_choice_id": winner[1] if winner else None,
                       "jev_choice_id": view["selection"].get(frame["frame_id"], {}).get("winner_id"),
                       "same_candidate": winner is not None and winner[1] ==
                       view["selection"].get(frame["frame_id"], {}).get("winner_id"),
                       "quality_ground_truth": None})
    return result


def compare_runs(root: Path = RUNS_ROOT) -> dict:
    index = analysis_snapshot(root)
    details = []
    fixture_checks = []
    group_for_run = {run_id: group["key"] for group in index["comparable_groups"]
                     for run_id in group["run_ids"]}
    for entry in index["runs"]:
        if entry.get("schema") != SCHEMA:
            continue
        store = LiveStore(entry["run_id"], create=False)
        try:
            view = store.snapshot()
        finally:
            store.close()
        detail = {"run_id": entry["run_id"],
                  "comparison_complete": bool(entry.get("comparison_complete")),
                  "saved_policy": _policy_comparison(view),
                  "fixed_evaluator": _fixed_evaluator(view)}
        if entry["run_id"] in group_for_run:
            details.append(detail)
        elif entry.get("origin") == "FIXTURE":
            fixture_checks.append(detail)
    profiles = defaultdict(list)
    for entry in index["runs"]:
        exp = entry.get("experiment") or {}
        group_key = group_for_run.get(entry["run_id"])
        if group_key is not None and exp.get("profile") in PROFILES:
            profiles[(group_key, exp["profile"])].append(entry)
    actual = []
    for (group_key, profile), runs in sorted(profiles.items()):
        first_mask = [x["first_mask_ms"] for r in runs for x in r["frame_latency"]
                      if x["first_mask_ms"] is not None]
        first_adoption = [x["first_adoption_ms"] for r in runs for x in r["frame_latency"]
                          if x["first_adoption_ms"] is not None]
        known_tokens = sum(r["recorded_input_tokens"] for r in runs)
        actual.append({"profile": profile, "comparable_group_key": group_key,
                       "run_ids": [r["run_id"] for r in runs],
                       "run_count": len(runs),
                       "complete_run_count": sum(bool(r.get("comparison_complete")) for r in runs),
                       "incomplete_run_count": sum(not r.get("comparison_complete") for r in runs),
                       "median_first_mask_ms": median(first_mask) if first_mask else None,
                       "median_first_adoption_ms": median(first_adoption) if first_adoption else None,
                       "peak_gpu_allocated_bytes": max(
                           (r["peak_gpu_allocated_bytes"] or 0 for r in runs), default=None),
                       "known_input_tokens": known_tokens,
                       "known_input_cost_usd": str(
                           Decimal(known_tokens) * Decimal("0.042") / Decimal(1000000)),
                       "unknown_usage_attempts": sum(r["missing_usage_attempts"] for r in runs),
                       "first_adoptions": sum(len(r["first_adoptions"]) for r in runs),
                       "final_adoptions": sum(bool(x) for r in runs for x in r["final_selection"].values()),
                       "segmentation_duration_ms": sum(r["segmentation_duration_ms"] for r in runs),
                       "failures": sum(r["job_counts"]["FAILED"] for r in runs),
                       "scope": "ACTUAL_SEPARATE_RUNS_WITH_RESOURCE_CONTENTION",
                       "quality_ground_truth": None})
    return {"index": index, "fixture_checks_excluded_from_live": fixture_checks,
            "saved_policy_comparison": details,
            "actual_configuration_comparison": actual,
            "evaluator_comparison": details,
            "quality_assessment": "NO_INDEPENDENT_GROUND_TRUTH"}

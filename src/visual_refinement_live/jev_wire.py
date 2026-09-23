"""Fixed five-axis Jev rubric, private-data renderer and raw Score validation."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from typing import Any

MODEL_ID = "jev-1.13.0"
RUBRIC_VERSION = "vr-instance-objects-jev-1.13-v1"
AXES = ("Q", "A", "R", "I", "C")
QUESTION_TEXT = {
    "Q": "How strongly do the supplied measurements support using this mask collection for the stated instance-object purpose? Judge evidence, not model reputation or speed.",
    "A": "How much important ambiguity, contradiction, or inability to distinguish objects remains in the supplied segmentation evidence?",
    "R": "How likely is the stated additional measurement or resegmentation to resolve the specifically identified uncertainty?",
    "I": "How relevant are these segmented regions to the stated observation purpose?",
    "C": "How well does the measured processing cost fit the stated operating constraints at this measurement time?",
}
CRITERIA = {
    "Q": [
        "The evidence shows clear conflict with the purpose or a serious defect.",
        "Evidence supporting use is scarce and observed problems dominate.",
        "Evidence is insufficient or ambiguous; suitability is not yet supported.",
        "Evidence supports use for the purpose without a major observed contradiction.",
        "Specific measurements strongly support use for the stated purpose.",
    ],
    "A": [
        "Enough comparison evidence exists and no important stated ambiguity remains.",
        "Only limited local ambiguity remains.",
        "Several ambiguities affect judgment or distinguishing evidence is missing.",
        "Major regions or boundaries remain unresolved.",
        "Severe contradictions or indistinguishable regions make interpretation highly uncertain.",
    ],
    "R": [
        "No additional problem is stated, or the proposed work lacks evidence of resolving it.",
        "Only weak evidence suggests the proposed work will resolve the problem.",
        "A problem and proposed work correspond, but the effect is unclear.",
        "There is a concrete reason the proposed work would reduce the problem.",
        "A specific measurement or operation would strongly distinguish and resolve the problem.",
    ],
    "I": [
        "The segmented regions have no apparent relation to the purpose.",
        "Only a peripheral relation to the purpose is supported.",
        "The regions relate to part of the purpose.",
        "The regions are directly relevant to achieving the purpose.",
        "The regions are central to the explicitly stated purpose.",
    ],
    "C": [
        "The measured result does not fit the strong stated operating constraints.",
        "Mismatch dominates across several operating constraints.",
        "Measured cost has both advantages and constraints.",
        "Measured conditions broadly fit the stated constraints.",
        "Evidence supports fitting the constraints with clear margin.",
    ],
}
QUESTIONS = {axis: {"type": "score", "instructions": QUESTION_TEXT[axis],
                    "criteria": CRITERIA[axis]} for axis in AXES}
FORBIDDEN_KEYS = {"path", "filename", "source_id", "pixel_sha256", "image_artifact_id",
                  "preview_artifact_id", "raw_artifact_id", "weight_sha256",
                  "architecture_label", "lane_id", "model", "score", "winner",
                  "video", "image", "mask", "audio", "api_key", "secret", "token"}


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("jev_state_depth")
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("jev_state_nonfinite")
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ValueError("jev_state_list_capacity")
        return [_sanitize(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 128:
            raise ValueError("jev_state_object_capacity")
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("jev_state_key_type")
            lower = key.lower()
            if lower in FORBIDDEN_KEYS or any(fragment in lower for fragment in ("api_key", "secret", "password", "filename", "path", "artifact_id", "weight_sha", "pixel_sha")):
                raise ValueError(f"jev_state_forbidden_field:{key}")
            result[key] = _sanitize(item, depth=depth + 1)
        return result
    raise ValueError("jev_state_value_type")


def build_state(candidate_id: str, measurement: dict, *,
                supplementary: dict | None = None) -> dict[str, Any]:
    """Use an anonymous candidate id and bounded local measurement facts only."""
    if not candidate_id.startswith("cand_") or len(candidate_id) > 96:
        raise ValueError("candidate_id_invalid")
    data = {
        "anonymous_candidate_id": sha256(candidate_id.encode()).hexdigest()[:20],
        "task": "Separate whole COCO instance objects from one image for inspection.",
        "quality_caveat": "No independent ground truth is provided. Geometry and image-edge statistics are proxies.",
        "measurements": {
            "mask_count": measurement["mask_count"],
            "area_fraction": measurement["area_fraction"],
            "union_coverage_fraction": measurement["union_coverage_fraction"],
            "overlap_pixels_fraction": measurement["overlap_pixels_fraction"],
            "component_count": measurement["component_count"],
            "tiny_instance_fraction": measurement["tiny_instance_fraction"],
            "tiny_instance_missing_reason": measurement["tiny_instance_missing_reason"],
            "hole_count": measurement["hole_count"],
            "bbox_fill_fraction": measurement["bbox_fill_fraction"],
            "boundary_image_edge_support": measurement["boundary_image_edge_support"],
            "inner_outer_color_delta": measurement["inner_outer_color_delta"],
            "inner_outer_color_missing_reason": measurement["inner_outer_color_missing_reason"],
            "roi_coverage_fraction": measurement["roi_coverage_fraction"],
            "outside_roi_fraction": measurement["outside_roi_fraction"],
            "timings_ms": measurement["timings_ms"],
        },
        "operating_constraints": {
            "gpu_job_deadline_ms": 120000,
            "gpu_permit": 1,
            "max_masks_per_candidate": 20,
        },
        "proposed_additional_work": "Compare this candidate with other completed masks at original coordinates to identify unmatched objects or boundary disagreement.",
    }
    if supplementary is not None:
        anonymous_pairs = []
        for pair in supplementary.get("pairs", []):
            role = ("LEFT" if candidate_id == pair["left"] else
                    "RIGHT" if candidate_id == pair["right"] else "OTHER_PAIR")
            anonymous_pairs.append({
                "status": pair["status"],
                "candidate_role": role,
                "union_symmetric_difference_fraction": pair.get("union_symmetric_difference_fraction"),
                "unmatched_self": pair.get(
                    "unmatched_left" if role == "LEFT" else "unmatched_right")
                    if role != "OTHER_PAIR" else None,
                "unmatched_other": pair.get(
                    "unmatched_right" if role == "LEFT" else "unmatched_left")
                    if role != "OTHER_PAIR" else None,
                "many_to_one_right": pair.get("many_to_one_right"),
            })
        data["supplementary"] = {"comparison_count": len(anonymous_pairs),
                                 "pairs": anonymous_pairs,
                                 "interpretation": "Disagreement is not ground truth."}
    return _sanitize(data)


def request_body(state: dict, axes: tuple[str, ...] = AXES) -> bytes:
    if not axes or len(set(axes)) != len(axes) or any(axis not in AXES for axis in axes):
        raise ValueError("jev_questions_invalid")
    body = {"model": MODEL_ID, "state": state, "questions": {axis: QUESTIONS[axis] for axis in axes}}
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")
    if len(data) > 32 * 1024:
        raise ValueError("jev_body_capacity")
    return data


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("score_number_type")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("score_number_invalid") from exc
    if not result.is_finite():
        raise ValueError("score_number_nonfinite")
    return result


def _quantization_half_step(number: Decimal) -> Decimal:
    if number in (0, 1):
        return Decimal(0)
    return Decimal(5).scaleb(min(number.as_tuple().exponent, -2) - 1)


def validate_score(answer: dict, axis: str) -> dict[str, Any]:
    """Check range, legend and distribution without silently fixing vendor values.

    The consistency bound is derived from the precision of each number printed
    in the response, capped at two decimal places per the official examples,
    rather than a broad hardcoded epsilon.
    """
    if answer.get("type") != "score":
        raise ValueError("answer_type")
    legend = answer.get("legend")
    if not isinstance(legend, dict) or {str(i): CRITERIA[axis][i] for i in range(5)} != legend:
        raise ValueError("score_legend_mismatch")
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != {str(i) for i in range(5)}:
        raise ValueError("score_distribution_keys")
    probs = [_decimal(probabilities[str(i)]) for i in range(5)]
    if any(value < 0 or value > 1 for value in probs):
        raise ValueError("score_probability_range")
    total = sum(probs)
    probability_bound = sum(_quantization_half_step(value) for value in probs)
    if abs(total - 1) > probability_bound:
        raise ValueError("score_probability_sum")
    score = _decimal(answer.get("score"))
    confidence = _decimal(answer.get("confidence"))
    if not 0 <= score <= 4 or not 0 <= confidence <= 1:
        raise ValueError("score_or_confidence_range")
    expected = sum(i * probs[i] for i in range(5))
    consistency_bound = (_quantization_half_step(score) +
                         sum(i * _quantization_half_step(probs[i]) for i in range(5)))
    if abs(score - expected) > consistency_bound:
        raise ValueError("score_distribution_mismatch")
    return {"axis_id": axis, "status": "VALID", "score_decimal": format(score, "f"),
            "confidence_decimal": format(confidence, "f"),
            "probabilities": {str(i): format(probs[i], "f") for i in range(5)},
            "validation_bound": format(consistency_bound, "f"),
            "validation_policy": "DISPLAY_QUANTIZATION_INTERVAL_V1"}


def validate_response(raw: bytes) -> dict:
    if len(raw) > 1024 * 1024:
        raise ValueError("response_size_limit")
    try:
        data = json.loads(raw, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("response_json_invalid") from exc
    if not isinstance(data, dict) or data.get("model") != MODEL_ID:
        raise ValueError("response_model_mismatch")
    answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) - set(AXES):
        raise ValueError("response_answers_invalid")
    axes = {}
    for axis in AXES:
        if axis not in answers:
            axes[axis] = {"axis_id": axis, "status": "MISSING",
                          "score_decimal": None, "missing_reason": "VENDOR_NOT_RETURNED"}
        else:
            try:
                axes[axis] = validate_score(answers[axis], axis)
            except (ValueError, TypeError, KeyError) as exc:
                axes[axis] = {"axis_id": axis, "status": "INVALID",
                              "score_decimal": None, "missing_reason": str(exc)}
    usage = data.get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("input_tokens"), int) or usage["input_tokens"] < 0:
        raise ValueError("response_usage_invalid")
    return {"model": MODEL_ID, "axes": axes, "usage": {"input_tokens": usage["input_tokens"],
                                                     "output_tokens": usage.get("output_tokens")},
            "raw_sha256": sha256(raw).hexdigest()}

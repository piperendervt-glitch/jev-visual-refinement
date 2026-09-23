"""SC04 wire tests use synthetic responses; they never call Jev."""
import json

import numpy as np

from src.visual_refinement_live.jev_wire import (
    AXES, CRITERIA, build_state, request_body, validate_response,
)
from src.visual_refinement_live.measurement import measure_candidate


def _answer(axis, score=3.5):
    return {"type": "score", "score": score, "confidence": 0.5,
            "legend": {str(i): CRITERIA[axis][i] for i in range(5)},
            "probabilities": {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.5, "4": 0.5}}


def test_renderer_sends_finite_statistics_and_no_private_refs():
    measurement = measure_candidate(np.zeros((4, 4, 3), np.uint8),
                                    np.zeros((0, 4, 4), np.uint8))
    state = build_state("cand_k1_s", measurement)
    wire = request_body(state)
    body = json.loads(wire)
    assert set(body["questions"]) == set(AXES)
    assert body["state"]["measurements"]["mask_count"] == 0
    assert "cand_k1_s" not in wire.decode()
    assert "pixel_sha256" not in wire.decode()
    assert "architecture_label" not in wire.decode()
    assert "api_key" not in wire.decode()


def test_partial_response_keeps_missing_separate_from_valid_q():
    raw = json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 400, "output_tokens": 10},
                      "answers": {"Q": _answer("Q")}}).encode()
    value = validate_response(raw)
    assert value["axes"]["Q"]["status"] == "VALID"
    assert value["axes"]["Q"]["score_decimal"] == "3.5"
    assert value["axes"]["A"]["status"] == "MISSING"


def test_distribution_mismatch_invalidates_only_affected_axis():
    raw = json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 400},
                      "answers": {"Q": _answer("Q", 3.9), "A": _answer("A")}}).encode()
    value = validate_response(raw)
    assert value["axes"]["Q"]["status"] == "INVALID"
    assert value["axes"]["A"]["status"] == "VALID"
    assert value["axes"]["Q"]["score_decimal"] is None

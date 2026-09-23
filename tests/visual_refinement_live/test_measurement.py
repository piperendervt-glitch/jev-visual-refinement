"""Focused geometry and evidence tests for the SC03 measurement boundary."""
import numpy as np
import pytest

from src.visual_refinement_live.measurement import measure_candidate, measure_disagreement


def test_real_geometry_uses_original_frame_denominators():
    image = np.zeros((20, 20, 3), np.uint8)
    image[2:8, 2:8] = 255
    masks = np.zeros((2, 20, 20), np.uint8)
    masks[0, 2:8, 2:8] = 1
    masks[1, 4:10, 4:10] = 1
    result = measure_candidate(image, masks)
    assert result["mask_count"] == 2
    assert result["union_coverage_fraction"] == 56 / 400
    assert result["overlap_pixels_fraction"] == 16 / 400
    assert result["area_fraction"]["median"] == 36 / 400
    assert result["coordinate_space"] == "ORIGINAL_KEYFRAME_PIXELS"
    assert result["profile"]["version"] == "instance-objects-measurement-v1"
    assert result["boundary_image_edge_support"]["max"] is not None


def test_empty_success_has_reasoned_missing_values():
    result = measure_candidate(np.zeros((8, 8, 3), np.uint8), np.zeros((0, 8, 8), np.uint8))
    assert result["mask_count"] == 0
    assert result["union_coverage_fraction"] == 0
    assert result["tiny_instance_fraction"] is None
    assert result["tiny_instance_missing_reason"] == "NO_INSTANCES"
    assert result["timings_ms"]["queue"]["reason"] == "NOT_INSTRUMENTED"


def test_pairwise_disagreement_tracks_unmatched_and_comparison_scope():
    left = np.zeros((2, 6, 6), np.uint8)
    right = np.zeros((1, 6, 6), np.uint8)
    left[0, 0:2, 0:2] = 1
    left[1, 4:6, 4:6] = 1
    right[0, 0:2, 0:2] = 1
    result = measure_disagreement({"a": left, "b": right})
    pair = result["pairs"][0]
    assert pair["unmatched_left"] == 1
    assert pair["unmatched_right"] == 0
    assert pair["union_symmetric_difference_fraction"] == 0.5
    assert pair["best_instance_matches"][0]["iou"] == 1
    assert result["interpretation"] == "DISAGREEMENT_NOT_GROUND_TRUTH"


def test_mismatched_coordinates_cannot_be_compared():
    with pytest.raises(ValueError, match="candidate_coordinate_mismatch"):
        measure_disagreement({"a": np.zeros((0, 2, 2), np.uint8),
                              "b": np.zeros((0, 3, 3), np.uint8)})

"""Versioned, local measurements for original-coordinate instance masks.

Measurements describe geometry and image agreement. They are not ground truth.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

import cv2
import numpy as np

PROFILE_VERSION = "instance-objects-measurement-v1"


@dataclass(frozen=True)
class MeasurementProfile:
    version: str = PROFILE_VERSION
    edge_low: int = 70
    edge_high: int = 140
    boundary_width_px: int = 2
    tiny_area_fraction: float = 0.001
    max_instances: int = 20
    max_pair_comparisons: int = 400
    color_ring_width_px: int = 3


PROFILE = MeasurementProfile()


def _finite_float(value: float) -> float | None:
    number = float(value)
    return round(number, 6) if np.isfinite(number) else None


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": _finite_float(min(values)),
        "median": _finite_float(float(np.median(values))),
        "max": _finite_float(max(values)),
    }


def _validate(rgb: np.ndarray, masks: np.ndarray, profile: MeasurementProfile) -> np.ndarray:
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("rgb8_required")
    if masks.ndim != 3 or masks.shape[1:] != rgb.shape[:2]:
        raise ValueError("mask_original_shape_mismatch")
    if len(masks) > profile.max_instances or not np.isin(masks, [0, 1]).all():
        raise ValueError("mask_binary_or_count")
    return masks.astype(bool, copy=False)


def _boundary(mask: np.ndarray, width: int) -> np.ndarray:
    kernel = np.ones((3, 3), np.uint8)
    image = mask.astype(np.uint8)
    interior = cv2.erode(image, kernel, iterations=width).astype(bool)
    return mask & ~interior


def measure_candidate(
    rgb: np.ndarray,
    masks: np.ndarray,
    *,
    roi: np.ndarray | None = None,
    timings_ms: dict[str, float | None] | None = None,
    profile: MeasurementProfile = PROFILE,
) -> dict[str, Any]:
    """Compute bounded summaries; empty masks are a successful measurement."""
    binary = _validate(rgb, masks, profile)
    height, width = rgb.shape[:2]
    area = height * width
    if roi is None:
        region = np.ones((height, width), dtype=bool)
        roi_kind = "FULL_FRAME"
    else:
        if roi.shape != (height, width) or not np.isin(roi, [0, 1]).all():
            raise ValueError("roi_invalid")
        region = roi.astype(bool, copy=False)
        if not region.any():
            raise ValueError("roi_empty")
        roi_kind = "EXPLICIT_BINARY"
    occupancy = binary.sum(axis=0, dtype=np.uint16)
    union = occupancy > 0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, profile.edge_low, profile.edge_high) > 0
    kernel = np.ones((3, 3), np.uint8)
    edge_near = cv2.dilate(edges.astype(np.uint8), kernel, iterations=profile.boundary_width_px).astype(bool)
    areas: list[float] = []
    fills: list[float] = []
    components: list[float] = []
    holes: list[float] = []
    edge_support: list[float] = []
    color_delta: list[float] = []
    boundaries: list[np.ndarray] = []
    for mask in binary:
        pixels = int(mask.sum())
        areas.append(pixels / area)
        count, _ = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
        components.append(float(max(0, count - 1)))
        contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        holes.append(float(sum(int(h[3] >= 0) for h in hierarchy[0])) if hierarchy is not None else 0.0)
        if pixels:
            ys, xs = np.nonzero(mask)
            box_area = (int(xs.max()) - int(xs.min()) + 1) * (int(ys.max()) - int(ys.min()) + 1)
            fills.append(pixels / box_area)
        else:
            fills.append(0.0)
        boundary = _boundary(mask, profile.boundary_width_px)
        boundaries.append(boundary)
        edge_support.append(float((boundary & edge_near).sum() / boundary.sum()) if boundary.any() else 0.0)
        outside = cv2.dilate(mask.astype(np.uint8), kernel, iterations=profile.color_ring_width_px).astype(bool) & ~mask
        if pixels and outside.any():
            inside_color = rgb[mask].mean(axis=0)
            outside_color = rgb[outside].mean(axis=0)
            color_delta.append(float(np.linalg.norm(inside_color - outside_color) / np.sqrt(3 * 255**2)))
    measured_timings = {}
    for key in ("queue", "load", "preprocess", "inference", "postprocess", "normalization", "measurement"):
        value = (timings_ms or {}).get(key)
        measured_timings[key] = {"value_ms": _finite_float(value), "reason": None} if value is not None else {
            "value_ms": None, "reason": "NOT_INSTRUMENTED"
        }
    measurement = {
        "profile": asdict(profile),
        "origin": "REAL_LOCAL_MEASUREMENT",
        "coordinate_space": "ORIGINAL_KEYFRAME_PIXELS",
        "units": {"area_fraction_denominator": "image_pixels", "roi_fraction_denominator": "roi_pixels",
                  "overlap_fraction_denominator": "image_pixels", "edge_support_denominator": "mask_boundary_pixels"},
        "mask_count": len(binary),
        "area_fraction": _summary(areas),
        "union_coverage_fraction": _finite_float(union.sum() / area),
        "overlap_pixels_fraction": _finite_float((occupancy >= 2).sum() / area),
        "component_count": _summary(components),
        "tiny_instance_fraction": _finite_float(sum(x < profile.tiny_area_fraction for x in areas) / len(areas)) if areas else None,
        "tiny_instance_missing_reason": None if areas else "NO_INSTANCES",
        "hole_count": _summary(holes),
        "bbox_fill_fraction": _summary(fills),
        "boundary_image_edge_support": _summary(edge_support),
        "inner_outer_color_delta": _summary(color_delta),
        "inner_outer_color_missing_reason": None if color_delta else "NO_VALID_INSIDE_OUTSIDE_RING",
        "roi_kind": roi_kind,
        "roi_coverage_fraction": _finite_float((union & region).sum() / region.sum()),
        "outside_roi_fraction": _finite_float((union & ~region).sum() / area),
        "timings_ms": measured_timings,
        "limitations": ["GEOMETRY_AND_IMAGE_PROXY_NOT_GROUND_TRUTH"],
    }
    measurement["digest"] = sha256(json.dumps(measurement, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return measurement


def measure_disagreement(
    candidate_masks: dict[str, np.ndarray],
    *,
    profile: MeasurementProfile = PROFILE,
) -> dict[str, Any]:
    """Compare two or more candidates without voting a majority into truth."""
    if len(candidate_masks) < 2:
        raise ValueError("two_candidates_required")
    shape = None
    for candidate_id, masks in candidate_masks.items():
        if not candidate_id or masks.ndim != 3 or len(masks) > profile.max_instances or not np.isin(masks, [0, 1]).all():
            raise ValueError("candidate_masks_invalid")
        shape = shape or masks.shape[1:]
        if masks.shape[1:] != shape:
            raise ValueError("candidate_coordinate_mismatch")
    pairs = []
    ids = sorted(candidate_masks)
    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1:]:
            left = candidate_masks[left_id].astype(bool)
            right = candidate_masks[right_id].astype(bool)
            if len(left) * len(right) > profile.max_pair_comparisons:
                pairs.append({"left": left_id, "right": right_id, "status": "NOT_MEASURED_CAPACITY"})
                continue
            left_union = np.any(left, axis=0) if len(left) else np.zeros(shape, bool)
            right_union = np.any(right, axis=0) if len(right) else np.zeros(shape, bool)
            union_area = int((left_union | right_union).sum())
            best = []
            matched_right = set()
            for li, lm in enumerate(left):
                choices = []
                for ri, rm in enumerate(right):
                    inter = int((lm & rm).sum())
                    union = int((lm | rm).sum())
                    choices.append((inter / union if union else 0.0, ri))
                score, ri = max(choices, default=(0.0, -1))
                best.append({"left_index": li, "right_index": ri if score > 0 else None,
                             "iou": _finite_float(score)})
                if score > 0:
                    matched_right.add(ri)
            pairs.append({
                "left": left_id, "right": right_id, "status": "MEASURED",
                "union_symmetric_difference_fraction": _finite_float(
                    np.logical_xor(left_union, right_union).sum() / union_area) if union_area else 0.0,
                "best_instance_matches": best,
                "unmatched_left": sum(x["right_index"] is None for x in best),
                "unmatched_right": len(right) - len(matched_right),
                "many_to_one_right": len(matched_right) < sum(x["right_index"] is not None for x in best),
            })
    output = {"profile_version": profile.version, "origin": "REAL_LOCAL_SUPPLEMENTARY_MEASUREMENT",
              "candidate_ids": ids, "pairs": pairs, "interpretation": "DISAGREEMENT_NOT_GROUND_TRUTH"}
    output["digest"] = sha256(json.dumps(output, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return output

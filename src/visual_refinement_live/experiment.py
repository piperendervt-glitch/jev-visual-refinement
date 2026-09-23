"""Finite fixed-profile experiment definitions and preflight arithmetic."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from .jev_wire import MODEL_ID, RUBRIC_VERSION
from .measurement import PROFILE_VERSION
from .segmenters import MODEL_SPEC

PROFILES = {"S": ("S",), "SAB": ("S", "A", "B"),
            "SABC": ("S", "A", "B", "C")}
APPROVED_K_SECONDS = (0.5, 2.0)
POLICY_VERSION = "q-max-same-context-threshold3-v1"
TASK_VERSION = "COCO_COMMON_INSTANCE_OBJECTS_V1"


@dataclass(frozen=True)
class ExperimentDefinition:
    task: str
    profiles: tuple[str, ...]
    k_seconds: tuple[float, ...]
    k_manifest: tuple[dict[str, Any], ...]
    repeats: int
    measurement_profile: str
    rubric_version: str
    selection_policy: str
    jev_model: str
    gpu_permit: int
    precision: str
    confidence: float
    max_instances: int
    cold_warm: str
    origin: str

    @property
    def digest(self) -> str:
        return sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def define_experiment(*, profiles: tuple[str, ...] = ("S", "SAB", "SABC"),
                      k_seconds: tuple[float, ...] = APPROVED_K_SECONDS,
                      repeats: int = 2, origin: str = "REAL",
                      k_manifest: tuple[dict[str, Any], ...] = ()) -> ExperimentDefinition:
    if not profiles or len(set(profiles)) != len(profiles) or any(p not in PROFILES for p in profiles):
        raise ValueError("profile_outside_fixed_set")
    if not k_seconds or len(set(k_seconds)) != len(k_seconds) or any(k not in APPROVED_K_SECONDS for k in k_seconds):
        raise ValueError("k_outside_approved_collection")
    if repeats not in (1, 2) or origin not in {"REAL", "FIXTURE"}:
        raise ValueError("experiment_quantity_invalid")
    if k_manifest and (len(k_manifest) != len(k_seconds) or
                       tuple(x.get("requested_seconds") for x in k_manifest) != k_seconds or
                       any(not isinstance(x.get("pts"), int) or
                           len(x.get("pixel_sha256", "")) != 64 for x in k_manifest)):
        raise ValueError("k_manifest_invalid")
    return ExperimentDefinition(TASK_VERSION, profiles, k_seconds, k_manifest, repeats,
                                PROFILE_VERSION, RUBRIC_VERSION, POLICY_VERSION,
                                MODEL_ID, 1, "FP32", 0.25, 20, "COLD_PER_RUN", origin)


def estimate(definition: ExperimentDefinition) -> dict[str, Any]:
    run_count = len(definition.profiles) * definition.repeats
    segmentation = sum(len(PROFILES[profile]) for profile in definition.profiles)
    segmentation *= len(definition.k_seconds) * definition.repeats
    e0 = segmentation
    e1 = sum(len(PROFILES[profile]) for profile in definition.profiles
             if len(PROFILES[profile]) >= 2) * len(definition.k_seconds) * definition.repeats
    suites = e0 + e1
    attempts = suites * 2
    questions = suites * 5 * 2
    reserved_micro_usd = attempts * 2688
    weight_manifest = {lane: {"architecture": MODEL_SPEC[lane]["architecture"],
                              "revision": MODEL_SPEC[lane]["revision"],
                              "sha256": MODEL_SPEC[lane].get("sha256"),
                              "sha256_prefix": MODEL_SPEC[lane].get("sha256_prefix")}
                       for lane in sorted({lane for p in definition.profiles for lane in PROFILES[p]})}
    return {"definition": asdict(definition), "definition_digest": definition.digest,
            "run_count": run_count, "segmentation_jobs": segmentation,
            "warmup_jobs": 0, "worst_case_gpu_duration_ms": segmentation * 120000,
            "e0_suites": e0, "e1_suites": e1, "logical_suites": suites,
            "max_questions": questions, "max_http_attempts": attempts,
            "max_request_bytes": 32 * 1024, "max_body_bytes": attempts * 32 * 1024,
            "max_reserved_micro_usd": reserved_micro_usd,
            "weight_manifest": weight_manifest,
            "storage_reservation_bytes": run_count * 100 * 1024**2,
            "quality_protocol": "BLINDED_VISUAL_REVIEW_IF_AVAILABLE_ELSE_UNKNOWN",
            "limitation": "ONLY_TWO_PREVIOUSLY_VIEWED_KEYFRAMES_EXPLORATORY"}

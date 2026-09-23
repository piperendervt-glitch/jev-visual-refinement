"""Approved live-runtime check before media decode, job reservation or network send."""
from __future__ import annotations

from importlib import metadata

from .segmenters import verify_weight, weight_path

SC02_PINS = {"av": "16.0.1", "torch": "2.9.1+cu128",
             "ultralytics": "8.4.160", "torchvision": "0.24.1+cu128"}
JEV_PIN = ("typesafe-sdk", "0.7.1")


def required_distributions(lanes: tuple[str, ...], *, jev: bool) -> dict[str, str]:
    if not lanes or any(lane not in {"S", "A", "B", "C"} for lane in lanes):
        raise ValueError("preflight_lanes_invalid")
    names = {"av": SC02_PINS["av"], "torch": SC02_PINS["torch"]}
    if set(lanes) & {"S", "A", "B"}:
        names["ultralytics"] = SC02_PINS["ultralytics"]
    if "C" in lanes:
        names["torchvision"] = SC02_PINS["torchvision"]
    if jev:
        names[JEV_PIN[0]] = JEV_PIN[1]
    return names


def verify_runtime(lanes: tuple[str, ...], *, jev: bool) -> dict:
    versions = {}
    for distribution, expected in required_distributions(lanes, jev=jev).items():
        try:
            installed = metadata.version(distribution)
        except metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"dependency_missing:{distribution}") from exc
        if installed != expected:
            raise RuntimeError(f"dependency_version_mismatch:{distribution}")
        versions[distribution] = installed
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise RuntimeError("approved_cuda_unavailable")
    device = torch.cuda.get_device_name(0)
    if "5060 Ti" not in device:
        raise RuntimeError("approved_gpu_mismatch")
    if jev:
        from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: F401
    weights = {}
    for lane in lanes:
        digest, size = verify_weight(lane, weight_path(lane))
        weights[lane] = {"sha256": digest, "bytes": size}
    return {"versions": versions, "device": device, "weights": weights}

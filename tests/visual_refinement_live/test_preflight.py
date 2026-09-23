"""No media or weights are touched when an approved runtime pin is missing."""
import pytest

from src.visual_refinement_live import preflight


def test_required_versions_match_selected_lanes_and_optional_jev():
    s = preflight.required_distributions(("S",), jev=False)
    assert set(s) == {"av", "torch", "ultralytics"}
    all_lanes = preflight.required_distributions(("S", "A", "B", "C"), jev=True)
    assert all_lanes["torchvision"] == "0.24.1+cu128"
    assert all_lanes["typesafe-sdk"] == "0.7.1"


def test_wrong_dependency_fails_before_weight_read_or_gpu_use(monkeypatch):
    monkeypatch.setattr(preflight.metadata, "version", lambda name: "wrong-version")
    monkeypatch.setattr(preflight, "verify_weight",
                        lambda *_: pytest.fail("weight must not be read"))
    with pytest.raises(RuntimeError, match="dependency_version_mismatch:av"):
        preflight.verify_runtime(("S",), jev=False)

"""Local weight provenance is checked before any model import or GPU work."""
from hashlib import sha256

import pytest

from src.visual_refinement_live import segmenters


def _synthetic_weight(tmp_path, monkeypatch):
    root = tmp_path / "models" / "sc03"
    root.mkdir(parents=True)
    weight = root / "synthetic.pt"
    payload = b"synthetic-weight"
    weight.write_bytes(payload)
    spec = dict(segmenters.MODEL_SPEC)
    spec["S"] = dict(spec["S"], bytes=len(payload), sha256=sha256(payload).hexdigest())
    monkeypatch.setattr(segmenters, "MODEL_SPEC", spec)
    monkeypatch.setattr(segmenters, "weight_path", lambda lane: weight)
    return weight, payload


def test_weight_verification_rejects_external_path(tmp_path, monkeypatch):
    weight, payload = _synthetic_weight(tmp_path, monkeypatch)
    assert segmenters.verify_weight("S", weight) == (sha256(payload).hexdigest(), len(payload))
    external = tmp_path / "outside.pt"
    external.write_bytes(payload)
    with pytest.raises(ValueError, match="weight_outside_owned_model_root"):
        segmenters.verify_weight("S", external)


def test_weight_verification_rejects_symlink_when_supported(tmp_path, monkeypatch):
    weight, payload = _synthetic_weight(tmp_path, monkeypatch)
    external = tmp_path / "outside.pt"
    external.write_bytes(payload)
    weight.unlink()
    try:
        weight.symlink_to(external)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    with pytest.raises(ValueError, match="weight_outside_owned_model_root"):
        segmenters.verify_weight("S", weight)

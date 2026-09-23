"""Pinned offline adapters for the common COCO instance-object task.

Imports and weight reads occur only when the live controller explicitly starts
after approval. There is no implicit model acquisition path.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import gc
import os
from pathlib import Path
import time

import numpy as np

from src.visual_refinement_sc02.masks import normalize_masks
from src.visual_refinement_sc02.segmenter import SegmentOutput

YOLO_REVISION = "5df55ae8af79be2d62706f481e97fea7c17c4afc"
MODEL_SPEC = {
    "S": {"architecture": "YOLO11n-seg", "filename": "yolo11n-seg.pt",
          "sha256": "55ed65c56c91713d23e8402371c6c49a6fd84f257f7dce452e8d70e41dcbe152",
          "bytes": 6_182_636, "revision": YOLO_REVISION, "license": "AGPL-3.0"},
    "A": {"architecture": "YOLO11s-seg", "filename": "yolo11s-seg.pt",
          "sha256": "1caa81c0195412efa411b632bcfb8c184939dddb6ae41f6a80c41b211ff257c3",
          "revision": YOLO_REVISION, "license": "AGPL-3.0"},
    "B": {"architecture": "YOLO11m-seg", "filename": "yolo11m-seg.pt",
          "sha256": "eb9a06f63e2206c35d68d839b08c362429ebecf933ad54c1ad68b2fd001c17cf",
          "revision": YOLO_REVISION, "license": "AGPL-3.0"},
    "C": {"architecture": "Mask R-CNN ResNet50-FPN COCO_V1",
          "filename": "maskrcnn_resnet50_fpn_coco-bf2d0c1e.pth",
          "sha256_prefix": "bf2d0c1e", "revision": "torchvision-0.24.1:COCO_V1",
          "license": "BSD-3-Clause"},
}
REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "cache" / "sc03_sc07"
MODELS = REPO / "models" / "sc03"
# COCO 80 contiguous YOLO indices mapped to COCO 2017 category IDs used by torchvision.
COCO80_CATEGORY_IDS = (
    1,2,3,4,5,6,7,8,9,10,11,13,14,15,16,17,18,19,20,21,22,23,24,25,
    27,28,31,32,33,34,35,36,37,38,39,40,41,42,43,44,46,47,48,49,50,
    51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,67,70,72,73,74,75,
    76,77,78,79,80,81,82,84,85,86,87,88,89,90)
assert len(COCO80_CATEGORY_IDS) == 80
COCO_CATEGORY_ID_SET = frozenset(COCO80_CATEGORY_IDS)

MAX_INSTANCES = 20
CONFIDENCE = 0.25


@dataclass(frozen=True)
class ModelProvenance:
    lane: str
    architecture: str
    revision: str
    weight_sha256: str
    weight_bytes: int
    license: str
    device: str
    load_ms: float


def weight_path(lane: str) -> Path:
    if lane not in MODEL_SPEC:
        raise ValueError("unknown_lane")
    root = REPO / "models" / "sc02" if lane == "S" else MODELS
    return root / MODEL_SPEC[lane]["filename"]


def verify_weight(lane: str, path: Path) -> tuple[str, int]:
    expected = weight_path(lane).absolute()
    if (path.absolute() != expected or path.is_symlink() or
            any(parent.is_symlink() or parent.is_junction()
                for parent in (expected.parent, expected.parent.parent))):
        raise ValueError("weight_outside_owned_model_root")
    actual = path.resolve(strict=True)
    if actual.parent != expected.parent.resolve(strict=True) or not actual.is_file():
        raise ValueError("weight_outside_owned_model_root")
    size = actual.stat().st_size
    if size <= 0 or size > 256 * 1024 * 1024:
        raise ValueError("weight_size_limit")
    digest = sha256(actual.read_bytes()).hexdigest()
    spec = MODEL_SPEC[lane]
    if ("bytes" in spec and size != spec["bytes"]) or (
        "sha256" in spec and digest != spec["sha256"]) or (
        "sha256_prefix" in spec and not digest.startswith(spec["sha256_prefix"])):
        raise ValueError("weight_integrity_mismatch")
    return digest, size


class _BaseAdapter:
    def __init__(self, lane: str, path: Path):
        if lane not in MODEL_SPEC:
            raise ValueError("unknown_lane")
        self.lane = lane
        digest, size = verify_weight(lane, path)
        self.weight_sha256 = digest
        self.weight_bytes = size
        self.device = "cuda:0"
        self.load_ms = 0.0
        self.model = None
        self.torch = None

    @property
    def provenance(self) -> ModelProvenance:
        spec = MODEL_SPEC[self.lane]
        return ModelProvenance(self.lane, spec["architecture"], spec["revision"],
                               self.weight_sha256, self.weight_bytes, spec["license"],
                               self.device, self.load_ms)

    def close(self) -> None:
        self.model = None
        gc.collect()
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


class YOLOAdapter(_BaseAdapter):
    def __init__(self, lane: str, path: Path):
        if lane not in ("S", "A", "B"):
            raise ValueError("yolo_lane_required")
        super().__init__(lane, path)
        os.environ["YOLO_OFFLINE"] = "1"
        os.environ["YOLO_CONFIG_DIR"] = str(CACHE / "ultralytics")
        import torch
        from ultralytics import YOLO, settings
        settings.update({"sync": False, "datasets_dir": str(CACHE / "datasets"),
                         "weights_dir": str(MODELS), "runs_dir": str(REPO / "runs" / "sc03_sc07"),
                         "clearml": False, "comet": False, "dvc": False, "mlflow": False,
                         "raytune": False, "tensorboard": False, "wandb": False})
        if not torch.cuda.is_available() or settings["sync"] is not False:
            raise RuntimeError("approved_offline_cuda_unavailable")
        self.torch = torch
        start = time.perf_counter()
        self.model = YOLO(str(path), task="segment")
        self.model.to("cuda:0")
        torch.cuda.synchronize(0)
        self.load_ms = (time.perf_counter() - start) * 1000
        if str(next(self.model.model.parameters()).device) != "cuda:0":
            raise RuntimeError("model_not_on_cuda_0")

    def predict(self, rgb: np.ndarray) -> SegmentOutput:
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("rgb8_required")
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        self.torch.cuda.synchronize(0)
        start = time.perf_counter()
        result = self.model.predict(bgr, device=0, imgsz=640, conf=CONFIDENCE, iou=0.7,
                                    max_det=MAX_INSTANCES, retina_masks=True, half=False,
                                    save=False, show=False, verbose=False)[0]
        self.torch.cuda.synchronize(0)
        duration = (time.perf_counter() - start) * 1000
        height, width = rgb.shape[:2]
        if result.orig_shape != (height, width):
            raise ValueError("result_original_shape_mismatch")
        result_device = str(result.boxes.data.device) if result.boxes is not None else self.device
        if result_device != "cuda:0":
            raise RuntimeError("result_not_on_cuda_0")
        native = (result.masks.data.detach().cpu().numpy() if result.masks is not None
                  else np.empty((0, height, width), np.uint8))
        norm_started = time.perf_counter()
        normalized = normalize_masks(native, width, height)
        normalization_ms = (time.perf_counter() - norm_started) * 1000
        boxes = (result.boxes.xyxy.detach().cpu().numpy() if result.boxes is not None
                 else np.empty((0, 4), np.float32))
        yolo_indices = (result.boxes.cls.detach().cpu().numpy() if result.boxes is not None
                        else np.empty((0,), np.float32))
        if np.any(yolo_indices != np.floor(yolo_indices)) or np.any(
                (yolo_indices < 0) | (yolo_indices >= len(COCO80_CATEGORY_IDS))):
            raise ValueError("yolo_class_outside_common_coco")
        classes = np.asarray([COCO80_CATEGORY_IDS[int(i)] for i in yolo_indices],
                             dtype=np.int32)
        confidence = (result.boxes.conf.detach().cpu().numpy() if result.boxes is not None
                      else np.empty((0,), np.float32))
        if len(normalized) != len(boxes):
            raise ValueError("mask_box_count_mismatch")
        timing = {key: (float(result.speed[key]) if result.speed and result.speed.get(key) is not None else None)
                  for key in ("preprocess", "inference", "postprocess")}
        timing["synchronized_predict_total"] = duration
        timing["normalization"] = normalization_ms
        return SegmentOutput(native, normalized, boxes, classes, confidence, "cuda:0", timing)


class MaskRCNNAdapter(_BaseAdapter):
    """Use only a verified local COCO_V1 state_dict; torchvision must not download."""

    def __init__(self, path: Path):
        super().__init__("C", path)
        import torch
        from torchvision.models.detection import maskrcnn_resnet50_fpn
        if not torch.cuda.is_available():
            raise RuntimeError("approved_cuda_unavailable")
        self.torch = torch
        start = time.perf_counter()
        model = maskrcnn_resnet50_fpn(weights=None, weights_backbone=None,
                                     min_size=640, max_size=960)
        state = torch.load(path, map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
        model.eval().to("cuda:0")
        torch.cuda.synchronize(0)
        self.load_ms = (time.perf_counter() - start) * 1000
        self.model = model

    def predict(self, rgb: np.ndarray) -> SegmentOutput:
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("rgb8_required")
        pre_started = time.perf_counter()
        tensor = self.torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float().div_(255).to("cuda:0")
        self.torch.cuda.synchronize(0)
        preprocess_ms = (time.perf_counter() - pre_started) * 1000
        start = time.perf_counter()
        with self.torch.inference_mode():
            prediction = self.model([tensor])[0]
        self.torch.cuda.synchronize(0)
        duration = (time.perf_counter() - start) * 1000
        allowed = self.torch.tensor(COCO80_CATEGORY_IDS, device=prediction["labels"].device)
        post_started = time.perf_counter()
        selected = self.torch.nonzero(
            (prediction["scores"] >= CONFIDENCE) &
            self.torch.isin(prediction["labels"], allowed)).flatten()[:MAX_INSTANCES]
        masks = prediction["masks"][selected, 0].detach().cpu().numpy()
        postprocess_ms = (time.perf_counter() - post_started) * 1000
        height, width = rgb.shape[:2]
        if masks.shape[1:] != (height, width):
            raise ValueError("mask_original_shape_mismatch")
        norm_started = time.perf_counter()
        normalized = normalize_masks(masks, width, height)
        normalization_ms = (time.perf_counter() - norm_started) * 1000
        boxes = prediction["boxes"][selected].detach().cpu().numpy()
        classes = prediction["labels"][selected].detach().cpu().numpy()
        confidences = prediction["scores"][selected].detach().cpu().numpy()
        return SegmentOutput(masks, normalized, boxes, classes, confidences,
                             "cuda:0", {"preprocess": preprocess_ms,
                                        "inference": duration,
                                        "postprocess": postprocess_ms,
                                        "normalization": normalization_ms,
                                        "synchronized_predict_total": duration})


def load_adapter(lane: str):
    path = weight_path(lane)
    return MaskRCNNAdapter(path) if lane == "C" else YOLOAdapter(lane, path)

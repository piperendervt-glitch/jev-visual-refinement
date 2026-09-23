"""One pinned, offline YOLO11n-seg CUDA adapter for SC02."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import time

import numpy as np

from .masks import normalize_masks

WEIGHT_SHA256 = "55ed65c56c91713d23e8402371c6c49a6fd84f257f7dce452e8d70e41dcbe152"
WEIGHT_BYTES = 6_182_636
WEIGHT_REVISION = "5df55ae8af79be2d62706f481e97fea7c17c4afc"


@dataclass(frozen=True)
class SegmentOutput:
    raw_masks: np.ndarray
    normalized_masks: np.ndarray
    boxes_xyxy: np.ndarray
    classes: np.ndarray
    confidences: np.ndarray
    device: str
    timings_ms: dict


class YOLO11Segmenter:
    def __init__(self, weight: Path):
        repo = Path(__file__).resolve().parents[2]
        os.environ["YOLO_OFFLINE"] = "1"
        os.environ["YOLO_CONFIG_DIR"] = str(repo / "cache" / "sc02" / "ultralytics")
        import torch
        from ultralytics import YOLO, settings
        settings.update({"sync": False, "datasets_dir": str(repo / "cache" / "sc02" / "datasets"),
                         "weights_dir": str(repo / "models" / "sc02"),
                         "runs_dir": str(repo / "runs" / "sc02"),
                         "clearml": False, "comet": False, "dvc": False,
                         "mlflow": False, "raytune": False, "tensorboard": False, "wandb": False})

        path = Path(weight).resolve(strict=True)
        if path.stat().st_size != WEIGHT_BYTES or sha256(path.read_bytes()).hexdigest() != WEIGHT_SHA256:
            raise ValueError("weight_integrity_mismatch")
        if settings["sync"] is not False:
            raise ValueError("ultralytics_sync_must_be_disabled")
        if not torch.cuda.is_available():
            raise RuntimeError("approved_cuda_unavailable")
        self.torch = torch
        started = time.perf_counter()
        self.model = YOLO(str(path), task="segment")
        self.model.to("cuda:0")
        torch.cuda.synchronize(0)
        self.load_ms = (time.perf_counter() - started) * 1000
        self.device = str(next(self.model.model.parameters()).device)
        if self.device != "cuda:0":
            raise RuntimeError("model_not_on_cuda_0")

    def predict(self, rgb: np.ndarray) -> SegmentOutput:
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("rgb8_required")
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        self.torch.cuda.synchronize(0)
        started = time.perf_counter()
        result = self.model.predict(bgr, device=0, imgsz=640, conf=0.25, iou=0.7,
                                    max_det=20, retina_masks=True, half=False,
                                    save=False, show=False, verbose=False)[0]
        self.torch.cuda.synchronize(0)
        total_ms = (time.perf_counter() - started) * 1000
        result_device = str(result.boxes.data.device) if result.boxes is not None else self.device
        if result_device != "cuda:0":
            raise RuntimeError("result_not_on_cuda_0")
        height, width = rgb.shape[:2]
        if result.orig_shape != (height, width):
            raise ValueError("result_original_shape_mismatch")
        native = (result.masks.data.detach().cpu().numpy() if result.masks is not None
                  else np.empty((0, height, width), dtype=np.uint8))
        normalized = normalize_masks(native, width, height)
        boxes = (result.boxes.xyxy.detach().cpu().numpy() if result.boxes is not None
                 else np.empty((0, 4), dtype=np.float32))
        classes = (result.boxes.cls.detach().cpu().numpy() if result.boxes is not None
                   else np.empty((0,), dtype=np.float32))
        confidences = (result.boxes.conf.detach().cpu().numpy() if result.boxes is not None
                       else np.empty((0,), dtype=np.float32))
        if len(boxes) != len(native):
            raise ValueError("mask_box_count_mismatch")
        speeds = result.speed or {}
        timings = {key: (float(speeds[key]) if speeds.get(key) is not None else None)
                   for key in ("preprocess", "inference", "postprocess")}
        timings["synchronized_predict_total"] = total_ms
        return SegmentOutput(native.astype(np.uint8, copy=True), normalized,
                             boxes.astype(np.float32, copy=True), classes.astype(np.int32, copy=True),
                             confidences.astype(np.float32, copy=True), result_device, timings)

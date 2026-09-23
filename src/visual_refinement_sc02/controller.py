"""Finite asynchronous SC02 run over one approved local video."""
from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
import threading
import time
import uuid

import numpy as np

from .masks import overlay_png, pixel_edge_bbox, png_mask, png_rgb
from .media import VideoInfo, decode_at, probe_video
from .segmenter import WEIGHT_REVISION, WEIGHT_SHA256, YOLO11Segmenter
from .store import RUNS_ROOT, RunStore

MAX_K = 3
MAX_JOBS = 12
MAX_WALL_SECONDS = 15 * 60


class RunController:
    def __init__(self, *, video: Path | None, run_id: str, weight: Path,
                 open_existing: bool = False):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.generation = 0
        self.accepting = not open_existing
        self.active_phase: str | None = None
        self.failure: str | None = None
        self.job_count = 0
        self.selected_count = 0
        self.started = time.monotonic()
        self.model = None
        self.weight = weight
        if open_existing:
            self.video = None
            self.store = RunStore(RUNS_ROOT / run_id, create=False)
            events = self.store.snapshot()["events"]
            self.job_count = sum(event["kind"] == "JobStarted" for event in events)
            self.selected_count = sum(event["kind"] == "KeyframeRequested" for event in events)
            self.generation = max((event["payload"].get("generation", 0) for event in events), default=0)
        else:
            if video is None:
                raise ValueError("approved_video_required")
            self.video = probe_video(video)
            self.store = RunStore(RUNS_ROOT / run_id, create=True,
                                  source={"source_id": self.video.source_id,
                                          "filename": self.video.path.name,
                                          "path": str(self.video.path),
                                          "byte_count": self.video.byte_count,
                                          "codec": self.video.codec,
                                          "width": self.video.display_width,
                                          "height": self.video.display_height,
                                          "duration_seconds": self.video.duration_seconds,
                                          "rotation_degrees": self.video.rotation_degrees})

    def _deadline(self) -> None:
        if time.monotonic() - self.started >= MAX_WALL_SECONDS:
            raise TimeoutError("run_deadline")

    def _phase(self, name: str, frame_id: str | None = None, data: dict | None = None) -> None:
        with self.lock:
            self.active_phase = name
            self.store.event(name, frame_id, data or {})

    def _job(self, frame_id: str, kind: str) -> int:
        with self.lock:
            if self.job_count >= MAX_JOBS:
                raise ValueError("job_limit")
            if time.monotonic() - self.started >= MAX_WALL_SECONDS:
                raise TimeoutError("run_deadline")
            self.job_count += 1
            number = self.job_count
            self.store.event("JobStarted", frame_id, {"job_number": number, "kind": kind, "lane": "S"})
            return number

    def select(self, seconds: float) -> str:
        with self.lock:
            if not self.accepting or self.video is None:
                raise ValueError("run_not_accepting")
            if self.worker is not None and self.worker.is_alive():
                raise ValueError("analysis_busy")
            if self.selected_count >= MAX_K:
                raise ValueError("keyframe_limit")
            if self.job_count + (2 if self.model is None else 1) > MAX_JOBS:
                raise ValueError("job_limit")
            if not 0 <= seconds < self.video.duration_seconds:
                raise ValueError("requested_time_out_of_range")
            self.generation += 1
            self.selected_count += 1
            generation = self.generation
            self.cancel.clear()
            frame_id = f"k_{generation}_{uuid.uuid4().hex[:8]}"
            self.store.event("KeyframeRequested", frame_id,
                             {"requested_seconds": seconds, "generation": generation})
            self.worker = threading.Thread(target=self._process, args=(frame_id, seconds, generation),
                                           name=f"sc02-{frame_id}", daemon=False)
            self.worker.start()
            return frame_id

    def _still_current(self, generation: int) -> bool:
        return generation == self.generation and not self.cancel.is_set()

    def _process(self, frame_id: str, seconds: float, generation: int) -> None:
        try:
            assert self.video is not None
            self._phase("DecodeStarted", frame_id, {"requested_seconds": seconds})
            decoded = decode_at(self.video, seconds)
            self._deadline()
            if not self._still_current(generation):
                self.store.event("JobCancelled", frame_id, {"stage": "DECODE"})
                return
            key_png = png_rgb(decoded.rgb)
            key_art = self.store.put_artifact(f"{frame_id}_key", ".png", key_png, "image/png")
            frame_data = {"frame_id": frame_id, "generation": generation,
                          "source_id": self.video.source_id,
                          "requested_seconds": seconds, "pts": decoded.pts,
                          "time_base": [decoded.time_base_num, decoded.time_base_den],
                          "actual_seconds": decoded.actual_seconds,
                          "seek_decode_ordinal": decoded.seek_decode_ordinal,
                          "sample_id": decoded.sample_id,
                          "width": decoded.width, "height": decoded.height,
                          "pixel_format": "RGB8_INTERLEAVED_TOP_LEFT_ROW_MAJOR",
                          "display_rotation_degrees": self.video.rotation_degrees,
                          "pixel_sha256": decoded.pixel_sha256,
                          "image_artifact_id": key_art["artifact_id"],
                          "image_file_sha256": key_art["sha256"]}
            self.store.publish_frame(frame_id, frame_data)
            if self.model is None:
                self._phase("ModelLoadStarted", frame_id)
                self.model = YOLO11Segmenter(self.weight)
                self._phase("ModelLoaded", frame_id,
                            {"device": self.model.device, "load_ms": self.model.load_ms})
                number = self._job(frame_id, "WARM_UP")
                self._phase("WarmupStarted", frame_id, {"job_number": number})
                warm = self.model.predict(decoded.rgb)
                self.store.event("JobFinished", frame_id,
                                 {"job_number": number, "kind": "WARM_UP", "device": warm.device,
                                  "duration_ms": warm.timings_ms["synchronized_predict_total"]})
            if not self._still_current(generation):
                self.store.event("JobCancelled", frame_id, {"stage": "SEGMENTATION"})
                return
            number = self._job(frame_id, "SEGMENTATION")
            self._phase("InferenceStarted", frame_id, {"job_number": number})
            output = self.model.predict(decoded.rgb)
            self._deadline()
            self.store.event("InferenceFinished", frame_id,
                             {"job_number": number, "device": output.device,
                              "timings_ms": output.timings_ms})
            if not self._still_current(generation):
                self.store.event("JobCancelled", frame_id, {"stage": "PUBLICATION", "job_number": number})
                return
            self._phase("NormalizationStarted", frame_id)
            candidate_id = f"{frame_id}_s"
            stream = BytesIO()
            np.savez_compressed(stream, masks=output.raw_masks, boxes_xyxy=output.boxes_xyxy,
                                classes=output.classes, confidences=output.confidences)
            raw_art = self.store.put_artifact(f"{candidate_id}_raw", ".npz", stream.getvalue(),
                                              "application/octet-stream")
            mask_records = []
            for ordinal, mask in enumerate(output.normalized_masks):
                mask_art = self.store.put_artifact(f"{candidate_id}_mask_{ordinal}", ".png",
                                                   png_mask(mask), "image/png")
                mask_records.append({"mask_id": f"{candidate_id}_{ordinal}", "ordinal": ordinal,
                                     "artifact_id": mask_art["artifact_id"],
                                     "bbox_xyxy": pixel_edge_bbox(mask),
                                     "class_id": int(output.classes[ordinal]),
                                     "confidence": float(output.confidences[ordinal]),
                                     "area_pixels": int(mask.sum())})
            preview_art = self.store.put_artifact(f"{candidate_id}_preview", ".png",
                                                  overlay_png(decoded.rgb, output.normalized_masks), "image/png")
            candidate = {"candidate_id": candidate_id, "frame_id": frame_id, "generation": generation,
                         "lane_id": "S", "origin": "REAL_MODEL", "architecture_label": "YOLO11n-seg",
                         "segmentation_status": "SUCCEEDED_NONEMPTY" if mask_records else "SUCCEEDED_EMPTY",
                         "mask_count": len(mask_records), "masks": mask_records,
                         "raw_artifact_id": raw_art["artifact_id"],
                         "preview_artifact_id": preview_art["artifact_id"],
                         "source_pixel_sha256": decoded.pixel_sha256,
                         "device": output.device, "backend": "Ultralytics/PyTorch",
                         "weight_revision": WEIGHT_REVISION, "weight_sha256": WEIGHT_SHA256,
                         "configuration": {"imgsz": 640, "precision": "FP32", "conf": 0.25,
                                           "iou": 0.7, "max_det": 20, "retina_masks": True,
                                           "input_color_conversion": "RGB8_TO_BGR8",
                                           "mask_threshold": 0.5,
                                           "source_transform": "ULTRALYTICS_LETTERBOX_INVERSE_TO_ORIGINAL",
                                           "rotation_degrees": self.video.rotation_degrees,
                                           "crop": None},
                         "timings_ms": output.timings_ms,
                         "evaluation": {axis: {"status": "NOT_REQUESTED", "score_decimal": None,
                                               "missing_reason": "REAL_JEV_OFF"}
                                        for axis in ("Q", "A", "R", "I", "C")}}
            seq = self.store.publish_candidate(candidate_id, frame_id, candidate)
            self.store.event("JobFinished", frame_id, {"job_number": number,
                             "kind": "SEGMENTATION", "candidate_id": candidate_id,
                             "mask_count": len(mask_records), "candidate_seq": seq})
            with self.lock:
                self.failure = None
                self.active_phase = "COMPLETE"
        except Exception as exc:
            with self.lock:
                self.failure = f"{type(exc).__name__}:{exc}"
                self.active_phase = "FAILED"
            self.store.event("JobFailed", frame_id, {"error_type": type(exc).__name__,
                             "error_code": str(exc)[:200]})

    def snapshot(self, cursor: int | None = None) -> dict:
        view = self.store.snapshot(cursor)
        view["source"].pop("path", None)
        with self.lock:
            view["active_phase"] = None if self.store.read_only else self.active_phase
            view["failure"] = self.failure
            view["job_count"] = self.job_count
            view["max_jobs"] = MAX_JOBS
            view["max_keyframes"] = MAX_K
            view["selected_count"] = self.selected_count
            view["accepting"] = self.accepting
            view["worker_alive"] = bool(self.worker and self.worker.is_alive())
            view["generation"] = self.generation
        return view

    def stop_analysis(self) -> None:
        with self.lock:
            self.generation += 1
            self.cancel.set()
            self.store.event("AnalysisStopRequested", None, {"generation": self.generation})

    def reset(self) -> None:
        with self.lock:
            if not self.accepting:
                raise ValueError("run_not_accepting")
            self.generation += 1
            self.cancel.set()
            self.store.event("RunReset", None, {"generation": self.generation})

    def close(self) -> dict:
        with self.lock:
            self.accepting = False
            self.cancel.set()
            worker = self.worker
        if worker is not None:
            worker.join(timeout=30)
        alive = bool(worker and worker.is_alive())
        if not self.store.read_only:
            current = self.store.snapshot()
            candidates = current["candidates"]
            failed = any(event["kind"] == "JobFailed" for event in current["events"])
            if failed:
                business = "PARTIAL_FAILURE" if candidates else "FAILED"
            elif candidates:
                business = ("COMPLETE_NONEMPTY" if any(c["mask_count"] > 0 for c in candidates)
                            else "COMPLETE_EMPTY")
            else:
                business = "CANCELLED_OR_UNEXECUTED"
            self.store.close_run(business, normal=not alive)
        summary = {"worker_alive": alive, "normal": not alive,
                   "business": self.store.get_meta("business")}
        self.store.close()
        return summary

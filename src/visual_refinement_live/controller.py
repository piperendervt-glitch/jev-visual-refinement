"""One active K, four independent completion-ordered segmentation lanes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import threading
import time
import uuid

import numpy as np

from src.visual_refinement_sc02.masks import overlay_png, pixel_edge_bbox, png_mask, png_rgb
from src.visual_refinement_sc02.media import decode_at, probe_video

from .measurement import measure_candidate, measure_disagreement, PROFILE_VERSION
from .segmenters import MODEL_SPEC, load_adapter
from .store import LiveStore

MAX_K = 2
MAX_JOB_SECONDS = 120
MAX_GPU_SECONDS = 2 * 60 * 60
MAX_GPU_BYTES = 13 * 1024**3
SHARED_GPU_PERMIT = threading.BoundedSemaphore(1)


class LiveController:
    """SC03 pipeline. Optional evaluator consumes committed E0/E1 after publication."""

    def __init__(self, *, video: Path | None, run_id: str, lanes: tuple[str, ...],
                 experiment: dict | None = None, open_existing: bool = False,
                 adapter_factory=load_adapter, evaluator=None, job_ledger=None,
                 origin: str = "REAL_MODEL", bucket: str = "VALIDATION",
                 plan_id: str | None = None, gpu_permit=None):
        if not lanes or len(set(lanes)) != len(lanes) or any(x not in MODEL_SPEC for x in lanes):
            raise ValueError("lanes_invalid")
        if origin not in {"REAL_MODEL", "FIXTURE"}:
            raise ValueError("origin_invalid")
        self.origin = origin
        self.experiment = experiment or {}
        self.lanes = lanes
        self.run_id = run_id
        self.lock = threading.RLock()
        self.gpu_permit = gpu_permit or SHARED_GPU_PERMIT
        self.bucket = bucket
        self.plan_id = plan_id
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.generation = 0
        self.selected_count = 0
        self.frame_generations: dict[str, int] = {}
        self.failure: str | None = None
        self.active_phase: str | None = None
        self.accepting = not open_existing
        self.adapter_factory = adapter_factory
        self.evaluator = evaluator
        self.job_ledger = job_ledger
        self.gpu_seconds = 0.0
        self.executor = None if open_existing else ThreadPoolExecutor(max_workers=len(lanes),
                                                                       thread_name_prefix="segment-lane")
        if open_existing:
            self.video = None
            self.store = LiveStore(run_id, create=False)
            snapshot = self.store.snapshot()
            self.selected_count = len(snapshot["frames"])
            self.generation = max((x.get("generation", 0) for x in snapshot["frames"]), default=0)
        else:
            if video is None:
                raise ValueError("approved_video_required")
            self.video = probe_video(video)
            source = {"source_id": self.video.source_id, "path": str(self.video.path),
                      "filename": self.video.path.name, "width": self.video.display_width,
                      "height": self.video.display_height, "duration_seconds": self.video.duration_seconds,
                      "byte_count": self.video.byte_count, "codec": self.video.codec}
            self.store = LiveStore(run_id, create=True, source=source, experiment=experiment or {})

    def _current(self, generation: int) -> bool:
        return not self.cancel.is_set() and self.accepting and generation == self.generation

    def _phase(self, kind: str, frame_id: str | None, lane: str | None = None,
               payload: dict | None = None) -> None:
        self.active_phase = kind
        self.store.event(kind, frame_id, lane, payload or {})

    def select(self, seconds: float) -> str:
        with self.lock:
            if not self.accepting or self.video is None:
                raise ValueError("run_not_accepting")
            if (self.worker and self.worker.is_alive()) or (self.evaluator is not None and self.evaluator.has_pending()):
                raise ValueError("active_k_limit")
            if self.selected_count >= MAX_K:
                raise ValueError("keyframe_limit")
            if not np.isfinite(seconds) or seconds < 0 or seconds >= self.video.duration_seconds:
                raise ValueError("requested_time_out_of_range")
            self.generation += 1
            self.selected_count += 1
            generation = self.generation
            self.cancel.clear()
            frame_id = f"k_{generation}_{uuid.uuid4().hex[:8]}"
            self.frame_generations[frame_id] = generation
            self.store.event("KeyframeRequested", frame_id, None,
                             {"requested_seconds": seconds, "generation": generation})
            self.worker = threading.Thread(target=self._process_k,
                                           args=(frame_id, seconds, generation),
                                           name=f"live-{frame_id}", daemon=False)
            self.worker.start()
            return frame_id

    def _process_k(self, frame_id: str, seconds: float, generation: int) -> None:
        try:
            assert self.video is not None
            self._phase("DecodeStarted", frame_id, payload={"seconds": seconds})
            decoded = decode_at(self.video, seconds)
            manifest = self.experiment.get("definition", {}).get("k_manifest", ())
            if manifest:
                expected = next((x for x in manifest
                                 if x.get("requested_seconds") == seconds), None)
                if (expected is None or expected["pts"] != decoded.pts or
                        expected["time_base"] != [decoded.time_base_num, decoded.time_base_den] or
                        expected["pixel_sha256"] != decoded.pixel_sha256):
                    raise ValueError("planned_k_fingerprint_mismatch")
            if not self._current(generation):
                self._phase("JobCancelled", frame_id, payload={"stage": "DECODE"})
                return
            key = self.store.put_artifact(f"{frame_id}_key", ".png",
                                          png_rgb(decoded.rgb), "image/png")
            frame = {"frame_id": frame_id, "generation": generation,
                     "source_id": self.video.source_id, "requested_seconds": seconds,
                     "pts": decoded.pts,
                     "time_base": [decoded.time_base_num, decoded.time_base_den],
                     "actual_seconds": decoded.actual_seconds,
                     "sample_id": decoded.sample_id,
                     "width": decoded.width, "height": decoded.height,
                     "pixel_sha256": decoded.pixel_sha256,
                     "pixel_format": "RGB8_INTERLEAVED_TOP_LEFT_ROW_MAJOR",
                     "image_artifact_id": key["artifact_id"]}
            self.store.frame(frame_id, frame)
            evidence0 = {"evidence_id": f"e_{frame_id}_0", "frame_id": frame_id,
                         "version": 0, "task": "COCO_COMMON_INSTANCE_OBJECTS_V1",
                         "measurement_profile": PROFILE_VERSION,
                         "comparison_set_refs": [], "dependencies": [],
                         "reason": "INITIAL_CANDIDATE_LOCAL_MEASUREMENTS"}
            self.store.evidence(evidence0["evidence_id"], frame_id, 0, evidence0)
            futures = {}
            for lane in self.lanes:
                job_id = f"seg_{frame_id}_{lane.lower()}"
                self.store.job(job_id, frame_id, lane, "SEGMENTATION", "SEGMENTATION_JOB")
                futures[self.executor.submit(self._lane, frame_id, decoded, lane,
                                             generation, job_id)] = lane
            completed: dict[str, np.ndarray] = {}
            for future in as_completed(futures):
                lane = futures[future]
                try:
                    output = future.result()
                    if output is not None:
                        completed[lane] = output
                except Exception as exc:
                    job_id = f"seg_{frame_id}_{lane.lower()}"
                    with self.store.lock:
                        row = self.store.db.execute(
                            "SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
                    if row and row[0] == "QUEUED":
                        self.store.job_state(job_id, "RUNNING", phase="ERROR")
                    if row and row[0] in {"QUEUED", "RUNNING"}:
                        self.store.job_state(job_id, "FAILED",
                                             error_code=f"{type(exc).__name__}:{str(exc)[:120]}")
                    self.failure = f"{type(exc).__name__}:{str(exc)[:160]}"
                    self.store.event("LaneFailed", frame_id, lane,
                                     {"error_type": type(exc).__name__, "error_code": str(exc)[:160]})
            if len(completed) >= 2 and self._current(generation):
                self._supplementary(frame_id, completed, generation)
            self.active_phase = "COMPLETE" if len(completed) == len(self.lanes) else "PARTIAL"
        except Exception as exc:
            self.failure = f"{type(exc).__name__}:{str(exc)[:160]}"
            self.active_phase = "FAILED"
            self.store.event("KFailed", frame_id, None,
                             {"error_type": type(exc).__name__, "error_code": str(exc)[:160]})

    def _lane(self, frame_id, decoded, lane: str, generation: int, job_id: str) -> np.ndarray | None:
        if not self._current(generation):
            self.store.job_state(job_id, "CANCELLED", error_code="GENERATION_CLOSED")
            return None
        start_wait = time.perf_counter()
        with self.gpu_permit:
            wait_ms = (time.perf_counter() - start_wait) * 1000
            if not self._current(generation):
                self.store.job_state(job_id, "CANCELLED", error_code="GENERATION_CLOSED")
                return None
            if self.gpu_seconds >= MAX_GPU_SECONDS:
                self.store.job_state(job_id, "EXPIRED", error_code="GPU_DEADLINE")
                return None
            if self.job_ledger is not None:
                try:
                    self.job_ledger.reserve_gpu_job(run_id=self.run_id, frame_id=frame_id,
                                                    lane_id=lane, bucket=self.bucket,
                                                    plan_id=self.plan_id, job_id=job_id)
                except ValueError as exc:
                    self.store.job_state(job_id, "EXPIRED", error_code=str(exc))
                    return None
            self.store.job_state(job_id, "RUNNING", phase="MODEL_LOAD")
            adapter = None
            began = time.perf_counter()
            try:
                self._phase("ModelLoadStarted", frame_id, lane)
                if self.origin == "REAL_MODEL":
                    import torch
                    torch.cuda.reset_peak_memory_stats(0)
                adapter = self.adapter_factory(lane)
                self._phase("ModelLoaded", frame_id, lane, asdict(adapter.provenance))
                if not self._current(generation):
                    self.store.job_state(job_id, "CANCELLED", error_code="GENERATION_CLOSED")
                    return None
                self._phase("InferenceStarted", frame_id, lane)
                output = adapter.predict(decoded.rgb)
                elapsed = time.perf_counter() - began
                self.gpu_seconds += elapsed
                if elapsed > MAX_JOB_SECONDS:
                    raise TimeoutError("gpu_job_deadline")
                allocated = adapter.torch.cuda.max_memory_allocated(0) if adapter.torch is not None else 0
                if allocated > MAX_GPU_BYTES:
                    raise MemoryError("gpu_peak_limit")
                self._phase("InferenceFinished", frame_id, lane,
                            {"timings_ms": output.timings_ms, "gpu_peak_allocated_bytes": allocated})
            except Exception as exc:
                self.store.job_state(job_id, "FAILED",
                                     error_code=f"{type(exc).__name__}:{str(exc)[:120]}")
                raise
            finally:
                try:
                    if adapter is not None:
                        adapter.close()
                finally:
                    if self.job_ledger is not None:
                        self.job_ledger.mark_gpu_job(
                            job_id, int((time.perf_counter() - began) * 1000))
        if not self._current(generation):
            self.store.job_state(job_id, "CANCELLED", error_code="GENERATION_CLOSED")
            return None
        candidate_id = f"cand_{frame_id}_{lane.lower()}"
        mask_records = []
        buffer = BytesIO()
        np.savez_compressed(buffer, masks=output.raw_masks, boxes_xyxy=output.boxes_xyxy,
                            classes=output.classes, confidences=output.confidences)
        raw = self.store.put_artifact(f"{candidate_id}_raw", ".npz",
                                      buffer.getvalue(), "application/octet-stream")
        for ordinal, mask in enumerate(output.normalized_masks):
            artifact = self.store.put_artifact(f"{candidate_id}_m{ordinal}", ".png",
                                               png_mask(mask), "image/png")
            mask_records.append({"mask_id": f"{candidate_id}_m{ordinal}",
                                 "artifact_id": artifact["artifact_id"],
                                 "bbox_xyxy": pixel_edge_bbox(mask),
                                 "class_id": int(output.classes[ordinal]),
                                 "confidence": float(output.confidences[ordinal]),
                                 "area_pixels": int(mask.sum())})
        preview = self.store.put_artifact(f"{candidate_id}_preview", ".png",
                                          overlay_png(decoded.rgb, output.normalized_masks), "image/png")
        provenance = adapter.provenance
        candidate = {"candidate_id": candidate_id, "frame_id": frame_id,
                     "lane_id": lane, "generation": generation, "origin": self.origin,
                     "architecture_label": provenance.architecture,
                     "weight_revision": provenance.revision,
                     "weight_sha256": provenance.weight_sha256,
                     "weight_bytes": provenance.weight_bytes,
                     "class_scheme": "COCO_2017_CATEGORY_ID",
                     "segmentation_status": "SUCCEEDED_NONEMPTY" if mask_records else "SUCCEEDED_EMPTY",
                     "mask_count": len(mask_records), "masks": mask_records,
                     "raw_artifact_id": raw["artifact_id"],
                     "preview_artifact_id": preview["artifact_id"],
                     "source_pixel_sha256": decoded.pixel_sha256,
                     "device": output.device, "timings_ms": output.timings_ms,
                     "gpu_queue_ms": wait_ms, "load_ms": provenance.load_ms,
                     "configuration": {"precision": "FP32", "confidence": 0.25,
                                       "max_instances": 20,
                                       "input_size": 640 if lane != "C" else "min640_max960",
                                       "task": "COCO_COMMON_INSTANCE_OBJECTS_V1"},
                     "evaluation": {axis: {"status": "NOT_REQUESTED", "score_decimal": None,
                                           "missing_reason": "REAL_JEV_OFF"}
                                    for axis in ("Q", "A", "R", "I", "C")}}
        cseq = self.store.candidate(candidate_id, frame_id, lane, candidate)
        measurement_started = time.perf_counter()
        measurement = measure_candidate(decoded.rgb, output.normalized_masks,
                                        timings_ms={"queue": wait_ms, "load": provenance.load_ms,
                                                    **output.timings_ms})
        measurement["timings_ms"]["measurement"] = {
            "value_ms": round((time.perf_counter() - measurement_started) * 1000, 6),
            "reason": None}
        measurement.pop("digest")
        measurement["digest"] = sha256(json.dumps(
            measurement, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if self.origin == "FIXTURE":
            measurement["origin"] = "FIXTURE_MEASUREMENT"
        measurement.update({"measurement_id": f"m_{frame_id}_{lane.lower()}_0",
                            "candidate_id": candidate_id, "frame_id": frame_id,
                            "lane_id": lane, "kind": "INITIAL", "candidate_seq": cseq})
        self.store.measurement(measurement["measurement_id"], frame_id, candidate_id,
                               measurement)
        self.store.job_state(job_id, "SUCCEEDED")
        if self.evaluator is not None and self._current(generation):
            self._queue_evaluation(frame_id, candidate, measurement,
                                   evidence_version=0)
        return output.normalized_masks

    def _queue_evaluation(self, frame_id: str, candidate: dict,
                          measurement: dict, *, evidence_version: int,
                          supplementary: dict | None = None) -> None:
        if self.evaluator is None:
            return
        try:
            self.evaluator.enqueue(frame_id, candidate, measurement,
                                   evidence_version=evidence_version,
                                   supplementary=supplementary)
        except Exception as exc:
            code = str(exc)
            category = "BUDGET_STOP" if any(x in code for x in
                ("budget", "plan_capacity", "capacity")) else "EVALUATION_QUEUE_ERROR"
            self.failure = category
            job_id = f"qfail_{candidate['candidate_id']}_e{evidence_version}"
            self.store.job(job_id, frame_id, candidate["lane_id"],
                           "EVALUATION", "EVALUATION_SUITE")
            if category == "BUDGET_STOP":
                self.store.job_state(job_id, "EXPIRED", error_code=category)
            else:
                self.store.job_state(job_id, "RUNNING", phase="QUEUE")
                self.store.job_state(job_id, "FAILED", error_code=category)
            self.store.event("EvaluationQueueFailed", frame_id, candidate["lane_id"],
                             {"candidate_id": candidate["candidate_id"],
                              "evidence_version": evidence_version,
                              "error_type": type(exc).__name__, "category": category})

    def _supplementary(self, frame_id: str, completed: dict[str, np.ndarray],
                       generation: int) -> None:
        job_id = f"sup_{frame_id}"
        self.store.job(job_id, frame_id, None, "MEASUREMENT", "SUPPLEMENTARY_JOB")
        self.store.job_state(job_id, "RUNNING", phase="PAIRWISE_COMPARISON")
        try:
            candidate_masks = {f"cand_{frame_id}_{lane.lower()}": mask for lane, mask in completed.items()}
            result = measure_disagreement(candidate_masks)
            if self.origin == "FIXTURE":
                result["origin"] = "FIXTURE_MEASUREMENT"
            result.update({"measurement_id": f"m_{frame_id}_supp", "frame_id": frame_id,
                           "kind": "SUPPLEMENTARY"})
            self.store.measurement(result["measurement_id"], frame_id, None, result)
            if self.evaluator is not None:
                # E0 requests were queued on each candidate publication. Let their
                # finite attempts settle before E1 invalidates that context.
                deadline = time.monotonic() + 45
                self._phase("AwaitingInitialEvaluation", frame_id)
                while (self._current(generation) and self.evaluator.has_pending()
                       and time.monotonic() < deadline):
                    time.sleep(0.05)
            if not self._current(generation):
                self.store.job_state(job_id, "CANCELLED", error_code="GENERATION_CLOSED")
                return
            evidence = {"evidence_id": f"e_{frame_id}_1", "frame_id": frame_id,
                        "version": 1, "previous_ref": f"e_{frame_id}_0",
                        "measurement_refs": [result["measurement_id"]],
                        "comparison_set_refs": sorted(candidate_masks),
                        "dependencies": [result["digest"]],
                        "reevaluation_targets": sorted(candidate_masks),
                        "task": "COCO_COMMON_INSTANCE_OBJECTS_V1",
                        "measurement_profile": PROFILE_VERSION}
            self.store.evidence(evidence["evidence_id"], frame_id, 1, evidence)
            self.store.job_state(job_id, "SUCCEEDED")
            if self.evaluator is not None and self._current(generation):
                for candidate_id in sorted(candidate_masks):
                    snapshot = self.store.snapshot()
                    candidate = next(x for x in snapshot["candidates"] if x["candidate_id"] == candidate_id)
                    initial = next(x for x in snapshot["measurements"] if x.get("candidate_id") == candidate_id)
                    self._queue_evaluation(frame_id, candidate, initial,
                                           evidence_version=1, supplementary=result)
        except Exception as exc:
            self.store.job_state(job_id, "FAILED", error_code=f"{type(exc).__name__}:{str(exc)[:120]}")
            raise

    def snapshot(self, cursor: int | None = None) -> dict:
        result = self.store.snapshot(cursor)
        result.update({"active_phase": self.active_phase if not self.store.read_only else None,
                       "failure": self.failure, "accepting": self.accepting,
                       "worker_alive": bool(self.worker and self.worker.is_alive()) or
                                       bool(self.evaluator is not None and self.evaluator.has_pending()),
                       "generation": self.generation, "selected_count": self.selected_count,
                       "max_keyframes": MAX_K, "lanes": list(self.lanes),
                       "gpu_seconds": round(self.gpu_seconds, 3)})
        return result

    def stop_analysis(self) -> None:
        with self.lock:
            self.generation += 1
            self.cancel.set()
            self.store.event("AnalysisStopRequested", None, None,
                             {"generation": self.generation})

    def close(self) -> dict:
        with self.lock:
            self.accepting = False
            self.cancel.set()
            worker = self.worker
        if worker:
            worker.join(timeout=MAX_JOB_SECONDS + 30)
        alive = bool(worker and worker.is_alive())
        if self.executor:
            self.executor.shutdown(wait=not alive, cancel_futures=alive)
        if self.evaluator is not None:
            self.evaluator.close()
        if not self.store.read_only:
            snapshot = self.store.snapshot()
            count = len(snapshot["candidates"])
            failures = sum(x["status"] == "FAILED" for x in snapshot["jobs"]) or int(
                self.failure is not None)
            business = ("PARTIAL_FAILURE" if count and failures else
                        "FAILED" if failures else
                        "COMPLETE_NONEMPTY" if any(x["mask_count"] for x in snapshot["candidates"]) else
                        "COMPLETE_EMPTY" if count else "CANCELLED_OR_UNEXECUTED")
            self.store.close_run(business, normal=not alive)
        result = {"worker_alive": alive, "normal": not alive,
                  "business": self.store.get_meta("business")}
        self.store.close()
        return result

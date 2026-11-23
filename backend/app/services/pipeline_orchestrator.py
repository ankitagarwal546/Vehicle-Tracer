"""Runs the forensic pipeline in a worker thread and publishes replayable progress."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import PIPELINE_VERSION, settings
from app.cv import attributes as attribute_module
from app.cv import make_model
from app.cv.clip_service import ClipService
from app.cv.detector_tracker import VehicleDetectorTracker, VehicleTrack, apply_stitching
from app.cv.device import active_device
from app.cv.frame_selection import reads_are_stable, select_plate_frames
from app.cv.model_assets import INSTALL_COMMAND, ModelsNotInstalled, asset_status, require_analysis_models
from app.cv.plate_fusion import FusedPlate, PlateRead, fuse_plate_reads
from app.cv.plate_ocr import PlateObservation, PlateReader
from app.cv.plate_variants import VARIANTS
from app.cv.reid import TrackProfile, link_tracks, mean_embedding, spatial_hsv_histogram
from app.cv.track_quality import assess_track
from app.cv.track_stitcher import plan_merges
from app.cv.video_processor import SamplingStats, probe_video, sample_frames, sha256_file
from app.db.database import SessionLocal
from app.db.models import AuditEvent, Case, Clip, CrossCameraEntity, RegistryVehicle, TrackedVehicle
from app.engine.matcher import RegistryIndex, match
from app.engine.schemas import (
    CharCandidate,
    LabelScore,
    MakeModelScore,
    PlateEvidence,
    QueryEvidence,
    RegistryRecord,
    SlotEvidence,
)

logger = logging.getLogger(__name__)
KEYFRAMES_PER_TRACK = 5
MAX_PLATE_MISSES = 6
MIN_FRAMES_IF_TRUNCATED = 8
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
EMBEDDING_BATCH = 32
COMMIT_EVERY_TRACKS = 3
ETA_MIN_PERCENT = 8.0
STAGE_LABELS = {
    "queued": "Queued", "models": "Loading models", "integrity": "Verifying evidence hashes",
    "tracking": "Detecting and tracking vehicles", "stitching": "Merging track fragments",
    "recognition": "Reading plates and attributes", "reid": "Comparing cameras",
    "report": "Finalising results", "done": "Complete", "failed": "Failed", "cancelled": "Cancelled",
}


class AnalysisCancelled(Exception):
    """Raised at a safe checkpoint after an investigator cancels a run."""


class ProgressBus:
    """Keeps each case's events so a late or reconnecting SSE client can replay them."""

    def __init__(self) -> None:
        self._events: dict[str, list[dict]] = {}
        self._started: dict[str, float] = {}
        self._lock = threading.Lock()

    def reset(self, case_id: str) -> None:
        with self._lock:
            self._events[case_id] = []
            self._started[case_id] = time.monotonic()

    def publish(self, case_id: str, stage: str, percent: float, message: str, status: str = "RUNNING",
                **extra) -> None:
        with self._lock:
            events = self._events.setdefault(case_id, [])
            elapsed = time.monotonic() - self._started.setdefault(case_id, time.monotonic())
            previous = events[-1]["percent"] if events else 0.0
            # Progress never moves backwards, except that a terminal failure keeps its last value.
            shown = max(percent, previous) if status == "RUNNING" else (100.0 if status == "COMPLETED" else previous)
            eta = round(elapsed * (100 - shown) / shown, 1) if status == "RUNNING" and shown >= ETA_MIN_PERCENT else None
            event = {"stage": stage, "stage_label": STAGE_LABELS.get(stage, stage), "percent": round(shown, 1),
                     "message": message, "status": status, "ts": time.time(), "elapsed_sec": round(elapsed, 1),
                     "eta_sec": eta, "seq": len(events), **extra}
            events.append(event)

    def since(self, case_id: str, cursor: int) -> list[dict]:
        with self._lock:
            return list(self._events.get(case_id, [])[cursor:])

    async def stream(self, case_id: str, fallback_status: str):
        cursor = 0
        idle = 0
        if not self.since(case_id, 0) and fallback_status in TERMINAL | {"CREATED", "READY"}:
            yield _sse({"stage": "idle", "percent": 100.0 if fallback_status == "COMPLETED" else 0.0,
                        "message": fallback_status, "status": fallback_status, "seq": 0})
            return
        while True:
            events = self.since(case_id, cursor)
            for event in events:
                cursor += 1
                yield _sse(event)
                if event["status"] in TERMINAL:
                    return
            idle = 0 if events else idle + 1
            if idle and idle % 40 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


progress_bus = ProgressBus()


class ModelHub:
    """Lazily loads heavy models once and records degraded states for the health endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.detector: VehicleDetectorTracker | None = None
        self.reader: PlateReader | None = None
        self.clip: ClipService | None = None
        self.detector_error: str | None = None

    def load(self) -> None:
        with self._lock:
            if self.detector is None:
                require_analysis_models()
                try:
                    self.detector = VehicleDetectorTracker()
                    self.detector_error = None
                except Exception as error:
                    self.detector_error = f"{type(error).__name__}: {error}"
                    raise RuntimeError(f"Vehicle detector could not be loaded: {self.detector_error}") from error
            if self.reader is None:
                reader = PlateReader()
                if reader.engine is None:
                    details = "; ".join(f"{name}: {error}" for name, error in reader.errors.items())
                    raise ModelsNotInstalled(f"No plate OCR engine could be loaded ({details}). "
                                             f"From the backend folder, run: {INSTALL_COMMAND}")
                self.reader = reader
            if self.clip is None:
                self.clip = ClipService()

    def status(self) -> dict:
        return {
            "detector": {"loaded": self.detector is not None,
                         "model": self.detector.weights_name if self.detector else settings.yolo_model,
                         "error": self.detector_error},
            "plate_ocr": {"loaded": bool(self.reader and self.reader.engine),
                          "engine": self.reader.name if self.reader else None,
                          "errors": self.reader.errors if self.reader else {}},
            "clip": {"loaded": bool(self.clip and self.clip.available), "model": settings.clip_model,
                     "error": self.clip.error if self.clip else None},
            "device": active_device(),
            "assets": asset_status(),
        }


models = ModelHub()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
_active: set[str] = set()
_cancel_flags: dict[str, threading.Event] = {}
_active_lock = threading.Lock()


def submit_case(case_id: str) -> bool:
    with _active_lock:
        if case_id in _active:
            return False
        _active.add(case_id)
        _cancel_flags[case_id] = threading.Event()
    progress_bus.reset(case_id)
    progress_bus.publish(case_id, "queued", 0, "Queued for analysis")
    _executor.submit(_run_guarded, case_id)
    return True


def is_running(case_id: str) -> bool:
    with _active_lock:
        return case_id in _active


def request_cancel(case_id: str) -> bool:
    with _active_lock:
        flag = _cancel_flags.get(case_id)
        if case_id not in _active or flag is None:
            return False
        flag.set()
    progress_bus.publish(case_id, "cancelling", 0, "Cancelling at the next safe checkpoint")
    return True


def _checkpoint(case_id: str) -> None:
    with _active_lock:
        flag = _cancel_flags.get(case_id)
    if flag is not None and flag.is_set():
        raise AnalysisCancelled()


def _abort_run(case_id: str, status: str, message: str) -> None:
    """Remove the unfinished run and leave the previous completed results and evidence intact."""
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        if case is None:
            return
        partial = 0
        run_id = None
        if case.live_run_id:
            partial = len([v for v in case.vehicles if v.run_id == case.live_run_id])
            session.execute(delete(TrackedVehicle).where(TrackedVehicle.case_id == case_id,
                                                         TrackedVehicle.run_id == case.live_run_id))
            session.execute(delete(CrossCameraEntity).where(CrossCameraEntity.case_id == case_id,
                                                            CrossCameraEntity.run_id == case.live_run_id))
        run_id = case.live_run_id
        case.live_run_id = None
        case.status = status
        case.error = message
        session.add(AuditEvent(case_id=case_id, actor="system", action=f"ANALYSIS_{status}",
                               note=f"{message} {partial} unfinished track(s) were discarded. "
                                    "Original evidence and any previous completed results are unchanged."))
        session.commit()
    if run_id:
        shutil.rmtree(settings.artifact_dir / case_id / run_id, ignore_errors=True)


def _run_guarded(case_id: str) -> None:
    try:
        _checkpoint(case_id)
        run_pipeline(case_id)
    except AnalysisCancelled:
        _abort_run(case_id, "CANCELLED", "Analysis was cancelled by the investigator.")
        progress_bus.publish(case_id, "cancelled", 0, "Analysis cancelled. No partial results were kept.", "CANCELLED")
    except Exception as error:
        logger.exception("Pipeline failed for case %s", case_id)
        message = f"{type(error).__name__}: {error}"
        _abort_run(case_id, "FAILED", message)
        progress_bus.publish(case_id, "failed", 0, f"Analysis failed: {error}", "FAILED")
    finally:
        with _active_lock:
            _active.discard(case_id)
            _cancel_flags.pop(case_id, None)


def recover_interrupted_runs(session: Session) -> int:
    """After a restart, drop unfinished runs and keep any earlier completed results."""
    cases = session.scalars(select(Case).where(Case.status.in_(["QUEUED", "RUNNING"]))).all()
    for case in cases:
        if case.live_run_id:
            session.execute(delete(TrackedVehicle).where(TrackedVehicle.case_id == case.id,
                                                         TrackedVehicle.run_id == case.live_run_id))
            session.execute(delete(CrossCameraEntity).where(CrossCameraEntity.case_id == case.id,
                                                            CrossCameraEntity.run_id == case.live_run_id))
            shutil.rmtree(settings.artifact_dir / case.id / case.live_run_id, ignore_errors=True)
        case.live_run_id = None
        case.status = "FAILED"
        case.error = "Interrupted by a server restart. Run the analysis again."
    session.commit()
    return len(cases)


_registry_cache: RegistryIndex | None = None
_registry_lock = threading.Lock()


def invalidate_registry() -> None:
    global _registry_cache
    with _registry_lock:
        _registry_cache = None


def load_registry(session: Session) -> RegistryIndex:
    """Return a cached column index so investigator re-ranks stay interactive."""
    global _registry_cache
    with _registry_lock:
        if _registry_cache is None:
            rows = session.scalars(select(RegistryVehicle)).all()
            _registry_cache = RegistryIndex(
                RegistryRecord(id=r.id, plate=r.plate, make=r.make, model=r.model, body_type=r.body_type,
                               colour=r.colour, year=r.year, owner_name=r.owner_name, owner_city=r.owner_city,
                               status=r.status, source=r.source) for r in rows
            )
        return _registry_cache


def build_query(plate: PlateEvidence, attrs: dict, plate_format: str = "latin_any") -> QueryEvidence:
    body = attrs.get("body_type") or {}
    make_models = [
        MakeModelScore(make=m["make"], model=m["model"], confidence=m["confidence"])
        for m in (attrs.get("make_model") or {}).get("predictions", []) if m["make"] != "Unknown"
    ]
    return QueryEvidence(
        plate=plate,
        colours=[LabelScore(label=c["label"], confidence=c["confidence"]) for c in attrs.get("colours", [])],
        body_type=body.get("label"),
        body_confidence=body.get("confidence", 0.0),
        make_models=make_models,
        plate_format=plate_format,
    )


@dataclass
class TrackAnalysis:
    track: VehicleTrack
    observations: list[PlateObservation]
    fused: FusedPlate
    attributes: dict
    embeddings: np.ndarray | None
    histogram: np.ndarray
    crops: list[np.ndarray]
    stacked_plate: np.ndarray | None = None
    plate_inspection: dict = field(default_factory=dict)


def _write_image(path: Path, image: np.ndarray, quality: int = 90, read_only: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if path.suffix == ".jpg" else []
    cv2.imwrite(str(path), image, params)
    if read_only:
        os.chmod(path, 0o444)
    return path.relative_to(settings.artifact_dir).as_posix()


def verify_clip_integrity(clip: Clip) -> None:
    """Refuse to analyse evidence that no longer matches its ingest hash."""
    stored = Path(clip.stored_path)
    source = stored.with_suffix(".zip") if stored.is_dir() else stored
    if not source.exists():
        raise ValueError(f"Evidence file for {clip.camera_label} is missing")
    if sha256_file(source) != clip.sha256:
        raise ValueError(f"Evidence file for {clip.camera_label} no longer matches its ingest SHA-256")


def _ensure_embeddings(observations: list) -> None:
    """Encode each crop once, in batches. Stitching and attributes then share the result."""
    if not models.clip.available:
        return
    missing = [item for item in observations if item.embedding is None]
    for start in range(0, len(missing), EMBEDDING_BATCH):
        batch = missing[start:start + EMBEDDING_BATCH]
        for item, vector in zip(batch, models.clip.encode_images([entry.crop for entry in batch])):
            item.embedding = vector


def _analyse_track(track: VehicleTrack, digits_only: bool = False, artifact_base: Path | None = None,
                   checkpoint=None) -> TrackAnalysis:
    observations = track.observations
    selection = select_plate_frames(observations)
    plate_results: list[PlateObservation] = []
    boxes_by_frame: dict[int, tuple[int, int, int, int]] = {}
    rejections: Counter = Counter()
    misses = inspected = 0
    stopped_stable = stopped_no_plate = 0
    for position, item in enumerate(selection.selected):
        if checkpoint:
            checkpoint()
        inspected += 1
        result, reason = models.reader.inspect_vehicle(item.crop, item.frame_idx, item.timestamp_sec,
                                                       item.target_in_crop, item.occluders_in_crop, item.crop_origin)
        if result is None:
            rejections[reason or "no plate"] += 1
            misses += 1
            if not plate_results and misses >= MAX_PLATE_MISSES:
                stopped_no_plate = len(selection.selected) - position - 1
                break  # The best views show no plate, so weaker views will not help.
            continue
        if artifact_base is not None:
            # Raw crops are lossless and read-only. Every later view is an additional artifact.
            result.read.crop = _write_image(artifact_base / f"plate_raw_f{item.frame_idx}.png", result.raw_crop,
                                            read_only=True)
        plate_results.append(result)
        boxes_by_frame[item.frame_idx] = result.bbox_in_crop
        if reads_are_stable([entry.read for entry in plate_results]):
            stopped_stable = len(selection.selected) - position - 1
            break
    reads = [result.read for result in plate_results]
    stacked_read, stacked = models.reader.read_stack(plate_results)
    if stacked_read is not None:
        reads.append(stacked_read)
    fused = fuse_plate_reads(reads, digits_only=digits_only)

    top = observations[:5]
    crops = [item.crop for item in top]
    boxes = [boxes_by_frame.get(item.frame_idx) for item in top]
    # White balance only needs global statistics, so a reduced decode is sufficient.
    scenes = [cv2.imdecode(np.frombuffer(item.frame_jpeg, np.uint8), cv2.IMREAD_REDUCED_COLOR_4) for item in top]
    colours = attribute_module.estimate_colour(crops, boxes, scenes)
    _ensure_embeddings(top)
    embeddings = np.stack([item.embedding for item in top]) if models.clip.available and top else None
    embedding = mean_embedding(embeddings)
    body = attribute_module.classify_body(track.yolo_class, track.yolo_confidence, embedding, models.clip)
    make = make_model.recognise(embedding, body["label"], models.clip)
    attrs = {"colours": colours, "body_type": body, "make_model": make, "yolo_class": track.yolo_class}
    inspection = {
        "candidate_frames": len(observations), "near_duplicates_skipped": selection.near_duplicates,
        "frames_inspected": inspected, "plates_read": len(plate_results),
        "skipped_plate_already_stable": stopped_stable, "skipped_no_plate_in_best_frames": stopped_no_plate,
        "rejections": dict(rejections),
    }
    return TrackAnalysis(track, plate_results, fused, attrs, embeddings, spatial_hsv_histogram(crops), crops, stacked,
                         inspection)


def _stitch_tracks(tracks: list[VehicleTrack]) -> tuple[list[VehicleTrack], int]:
    """Merge identity switches, then drop tracks too short or too clipped to be evidence."""
    leading = {track.track_id: track.observations[:3] for track in tracks}
    _ensure_embeddings([item for group in leading.values() for item in group])
    vectors: dict[int, np.ndarray] = {}
    for track in tracks:
        group = leading[track.track_id]
        if models.clip.available and group:
            vectors[track.track_id] = mean_embedding(np.stack([item.embedding for item in group]))
        else:
            vectors[track.track_id] = spatial_hsv_histogram([item.crop for item in group])

    def appearance(a, b) -> float:
        return float(vectors[a.track_id] @ vectors[b.track_id])

    decisions = plan_merges(tracks, appearance)
    stitched = apply_stitching(tracks, decisions)
    kept = [
        track for track in stitched
        if track.frames_tracked >= settings.min_track_frames
        and not (track.mostly_truncated and track.frames_tracked < MIN_FRAMES_IF_TRUNCATED)
    ]
    return kept, len(decisions)


def _persist_track(session: Session, case: Case, clip: Clip, analysis: TrackAnalysis, registry: RegistryIndex,
                   base: Path, run_id: str | None = None) -> tuple[TrackedVehicle, TrackProfile]:
    track = analysis.track
    vehicle = TrackedVehicle(case_id=case.id, clip_id=clip.id, run_id=run_id, track_id=track.track_id,
                             first_seen_sec=round(track.first_seen_sec, 3),
                             last_seen_sec=round(track.last_seen_sec, 3), frames_tracked=track.frames_tracked)
    session.add(vehicle)
    session.flush()
    by_frame = {obs.read.frame_idx: obs for obs in analysis.observations}
    observations = track.observations
    ordered = sorted(observations, key=lambda o: (
        o.frame_idx not in by_frame,
        -(by_frame[o.frame_idx].quality * by_frame[o.frame_idx].read.bbox_area) if o.frame_idx in by_frame else 0.0,
        o.truncated,
        -o.sharpness,
    ))
    keyframes: list[dict] = []
    for index, item in enumerate(ordered[:KEYFRAMES_PER_TRACK]):
        frame = cv2.imdecode(np.frombuffer(item.frame_jpeg, np.uint8), cv2.IMREAD_COLOR)
        x1, y1, x2, y2 = (int(round(value * item.scene_scale)) for value in item.bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 255), 2)
        label = f"T{track.track_id} {item.timestamp_sec:.2f}s"
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        top = max(y1 - label_h - 6, 0)
        cv2.rectangle(frame, (x1, top), (x1 + label_w + 6, top + label_h + 6), (0, 220, 255), -1)
        cv2.putText(frame, label, (x1 + 3, top + label_h + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1,
                    cv2.LINE_AA)
        entry = {
            "frame_idx": item.frame_idx,
            "timestamp_sec": round(item.timestamp_sec, 3),
            "sharpness": round(item.sharpness, 2),
            "frame_sharpness": round(item.frame_sharpness, 2),
            "brightness": round(item.frame_brightness, 1),
            "contrast": round(item.frame_contrast, 1),
            "low_sharpness": item.low_sharpness,
            "bbox": list(item.bbox),
            "frame": _write_image(base / f"frame_{index}.jpg", frame, 82),
            "crop": _write_image(base / f"crop_{index}.jpg", item.crop),
        }
        plate = by_frame.get(item.frame_idx)
        if plate:
            views = []
            for name, info in VARIANTS.items():
                image = plate.variants.get(name)
                if image is None:
                    continue
                output = plate.variant_outputs.get(name)
                path = plate.read.crop if name == "raw" else _write_image(base / f"plate_f{item.frame_idx}_{name}.png", image)
                views.append({"name": name, "label": info["label"], "kind": info["kind"], "image": path,
                              "width": int(image.shape[1]), "height": int(image.shape[0]),
                              "ocr_read": name in plate.variants_read,
                              "text": output.text if output else "",
                              "mean_confidence": round(output.score, 4) if output else 0.0})
            enhanced = next(view["image"] for view in views if view["name"] == "gray_clahe")
            entry.update({
                "plate_raw": plate.read.crop,
                "plate_enhanced": enhanced,
                "plate_text": plate.read.raw_text,
                "plate_quality": round(plate.quality, 3),
                "plate_box_confidence": round(plate.box_confidence, 4),
                "plate_crop_size": [int(plate.raw_crop.shape[1]), int(plate.raw_crop.shape[0])],
                "plate_box_source": list(plate.box_in_source) if plate.box_in_source else None,
                "image_warnings": plate.image_warnings,
                "crop_sha256": plate.read.crop_sha256,
                "ocr_engine": plate.read.ocr_engine,
                "ocr_source": plate.read.source,
                "rectification": plate.rectification.as_dict(),
                "variants": views,
            })
        keyframes.append(entry)

    evidence = analysis.fused.to_evidence()
    query = build_query(evidence, analysis.attributes, clip.plate_format)
    vehicle.best_crop = keyframes[0]["crop"] if keyframes else None
    vehicle.keyframes = keyframes
    vehicle.plate_reads = [{**_read_dict(obs.read), "plate_box_confidence": round(obs.box_confidence, 4),
                            "plate_crop_size": [int(obs.raw_crop.shape[1]), int(obs.raw_crop.shape[0])],
                            "plate_box_source": list(obs.box_in_source) if obs.box_in_source else None,
                            "variants_read": list(obs.variants_read), "image_warnings": obs.image_warnings,
                            "rectification": obs.rectification.status} for obs in analysis.observations]
    vehicle.fused_plate = {
        **analysis.fused.to_dict(),
        "stack_crop": _write_image(base / "plate_stack.png", analysis.stacked_plate)
        if analysis.stacked_plate is not None else None,
    }
    vehicle.attributes = {
        **analysis.attributes,
        "partial_view": track.mostly_truncated,
        "merged_track_ids": track.merged_track_ids,
        "track_quality": {**assess_track(track), "plate_inspection": analysis.plate_inspection},
    }
    vehicle.ai_evidence = query.model_dump()
    vehicle.active_evidence = query.model_dump()
    vehicle.match_result = match(query, registry).model_dump()
    vehicle.overrides = {}

    start = end = None
    if clip.recorded_at:
        recorded = clip.recorded_at if clip.recorded_at.tzinfo else clip.recorded_at.replace(tzinfo=timezone.utc)
        start, end = recorded + timedelta(seconds=track.first_seen_sec), recorded + timedelta(seconds=track.last_seen_sec)
    make_models = (analysis.attributes["make_model"] or {}).get("predictions", [])
    profile = TrackProfile(
        vehicle_id=vehicle.id, clip_id=clip.id, embedding=mean_embedding(analysis.embeddings),
        histogram=analysis.histogram, plate_text=analysis.fused.text,
        body_type=analysis.attributes["body_type"]["label"], colours=analysis.attributes["colours"],
        make_models=make_models, start=start, end=end, location=clip.location,
        latitude=clip.latitude, longitude=clip.longitude, plate_format=clip.plate_format,
    )
    return vehicle, profile


def _read_dict(read: PlateRead) -> dict:
    return {"frame_idx": read.frame_idx, "timestamp_sec": round(read.timestamp_sec, 3), "raw_text": read.raw_text,
            "char_confidences": [round(v, 4) for v in read.char_confidences],
            "char_alternatives": [[[c, round(p, 4)] for c, p in slot] for slot in read.char_alternatives],
            "char_source_supported": read.char_source_supported, "char_variants": read.char_variants,
            "sharpness_score": round(read.sharpness_score, 3), "bbox_area": read.bbox_area,
            "ocr_engine_score": round(read.ocr_engine_score, 4), "source": read.source, "derived": read.derived,
            "ocr_engine": read.ocr_engine, "crop": read.crop, "crop_sha256": read.crop_sha256}


def _read_from_dict(item: dict) -> PlateRead:
    return PlateRead(
        item["frame_idx"], item["timestamp_sec"], item["raw_text"], item["char_confidences"],
        item["sharpness_score"], item["bbox_area"], item["ocr_engine_score"], item.get("source", ""),
        item.get("derived", False),
        [[(c, p) for c, p in slot] for slot in item.get("char_alternatives", [])],
        item.get("char_source_supported", []), item.get("char_variants", []), item.get("ocr_engine", ""),
        item.get("crop"), item.get("crop_sha256"),
    )


def _flag_repeated_plates(vehicles: list[TrackedVehicle]) -> int:
    """Flag, but do not merge, different tracks in one clip that read the same complete plate."""
    groups: dict[tuple[str, str], list[TrackedVehicle]] = {}
    for vehicle in vehicles:
        text = (vehicle.fused_plate or {}).get("text", "")
        if len(text) >= 6 and "?" not in text:
            groups.setdefault((vehicle.clip_id, text), []).append(vehicle)
    flagged = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        for member in members:
            others = ", ".join(f"T{other.track_id}" for other in members if other is not member)
            quality = dict(member.attributes["track_quality"])
            quality["tier"] = "review"
            quality["reasons"] = [*quality["reasons"], f"same plate also read on {others}"]
            member.attributes = {**member.attributes, "track_quality": quality}
            flagged += 1
    return flagged


def _build_entities(session: Session, case: Case, vehicles: dict[str, TrackedVehicle],
                    profiles: list[TrackProfile], registry: RegistryIndex,
                    run_id: str | None = None) -> tuple[int, int]:
    groups, links, blocked = link_tracks(profiles)
    tier_order = ["partial_plate", "strong_plate"]
    for group in groups:
        members = [vehicles[vehicle_id] for vehicle_id in group]
        merged_reads: list[PlateRead] = []
        for member in members:
            merged_reads.extend(_read_from_dict(item) for item in member.plate_reads)
        fused = fuse_plate_reads(merged_reads, digits_only=any(m.clip.plate_format == "non_latin_digits" for m in members))
        best = max(members, key=lambda v: v.frames_tracked)
        formats = {m.clip.plate_format for m in members} - {"latin_any"}
        query = build_query(fused.to_evidence(), best.attributes, formats.pop() if len(formats) == 1 else "latin_any")
        timeline = []
        for member in members:
            clip = member.clip
            absolute = None
            if clip.recorded_at:
                recorded = clip.recorded_at if clip.recorded_at.tzinfo else clip.recorded_at.replace(tzinfo=timezone.utc)
                absolute = (recorded + timedelta(seconds=member.first_seen_sec)).isoformat()
            timeline.append({
                "vehicle_id": member.id, "clip_id": clip.id, "camera_label": clip.camera_label,
                "location": clip.location, "timezone": clip.timezone, "first_seen_sec": member.first_seen_sec,
                "last_seen_sec": member.last_seen_sec, "absolute_time": absolute,
                "plate": member.fused_plate.get("text", ""), "best_crop": member.best_crop,
            })
        timeline.sort(key=lambda t: (t["absolute_time"] is None, t["absolute_time"] or "", t["first_seen_sec"]))
        group_links = [link for link in links if link["a"] in group and link["b"] in group]
        entity = CrossCameraEntity(
            case_id=case.id, run_id=run_id, fused_plate=fused.to_dict(), timeline=timeline, links=group_links,
            match_result=match(query, registry).model_dump(), review_status="proposed",
            evidence_tier=min((link["evidence_tier"] for link in group_links), key=tier_order.index),
        )
        session.add(entity)
        session.flush()
        for member in members:
            member.entity_id = entity.id
    return len(groups), blocked


def _plate_from_fused(fused: dict) -> PlateEvidence:
    slots = [
        SlotEvidence(char=slot["char"], confidence=slot["confidence"] if slot["char"] != "?" else 0.0,
                     candidates=[CharCandidate(char=c["char"], probability=c["probability"])
                                 for c in slot.get("candidates", [])])
        for slot in fused.get("slots", [])
    ]
    return PlateEvidence(slots=slots, anchor="full" if len(slots) >= 9 else "floating")


def rescore_case(session: Session, case: Case, actor: str = "Investigator") -> dict:
    """Compare existing OCR evidence with the current registry. OCR evidence is not modified."""
    registry = load_registry(session)
    before = Counter((v.match_result or {}).get("outcome") for v in case.completed_vehicles)
    for vehicle in case.completed_vehicles:
        evidence = QueryEvidence.model_validate(vehicle.active_evidence)
        evidence.plate_format = vehicle.clip.plate_format
        vehicle.active_evidence = evidence.model_dump()
        vehicle.match_result = match(evidence, registry).model_dump()
    for entity in case.completed_entities:
        members = [v for v in entity.vehicles if v.run_id == case.active_run_id]
        if not members:
            continue
        formats = {m.clip.plate_format for m in members} - {"latin_any"}
        best = max(members, key=lambda v: v.frames_tracked)
        query = build_query(_plate_from_fused(entity.fused_plate), best.attributes,
                            formats.pop() if len(formats) == 1 else "latin_any")
        entity.match_result = match(query, registry).model_dump()
    after = Counter((v.match_result or {}).get("outcome") for v in case.completed_vehicles)
    case.runtime = {**(case.runtime or {}), "registry_fingerprint": registry.fingerprint()}
    session.add(AuditEvent(case_id=case.id, actor=actor, action="REGISTRY_RESCORED",
                           note=f"OCR evidence unchanged. Outcomes before: {dict(before)}. After: {dict(after)}."))
    session.commit()
    return {"before": dict(before), "after": dict(after), "tracks": len(case.completed_vehicles)}


def refresh_legacy_results(session: Session) -> int:
    """Re-score stored results from older releases so outdated verdicts are never displayed."""
    registry = load_registry(session)
    updated = 0
    for vehicle in session.scalars(select(TrackedVehicle)).all():
        if "registry_coverage" in (vehicle.match_result or {}) or not vehicle.active_evidence:
            continue
        vehicle.match_result = match(QueryEvidence.model_validate(vehicle.active_evidence), registry).model_dump()
        updated += 1
    for entity in session.scalars(select(CrossCameraEntity)).all():
        if "registry_coverage" in (entity.match_result or {}) or not entity.vehicles:
            continue
        best = max(entity.vehicles, key=lambda v: v.frames_tracked)
        formats = {v.clip.plate_format for v in entity.vehicles} - {"latin_any"}
        query = build_query(_plate_from_fused(entity.fused_plate), best.attributes,
                            formats.pop() if len(formats) == 1 else "latin_any")
        entity.match_result = match(query, registry).model_dump()
        if "outcome" not in (entity.match_result or {}):
            entity.review_status = "proposed"
            entity.evidence_tier = "legacy_unverified"
        updated += 1
    session.commit()
    return updated


def run_pipeline(case_id: str) -> None:
    def publish(stage: str, pct: float, msg: str, **extra) -> None:
        progress_bus.publish(case_id, stage, pct, msg, **extra)

    def checkpoint() -> None:
        _checkpoint(case_id)

    publish("models", 2, "Loading computer vision models")
    models.load()
    checkpoint()
    started = time.perf_counter()
    stage_seconds: Counter = Counter()

    with SessionLocal() as session:
        case = session.get(Case, case_id)
        if case is None:
            raise ValueError("Case not found")
        clips = list(case.clips)
        if not clips:
            raise ValueError("Case has no clips")
        publish("integrity", 3, f"Verifying SHA-256 for {len(clips)} clip(s)")
        mark = time.perf_counter()
        for clip in clips:
            verify_clip_integrity(clip)
        stage_seconds["integrity"] += time.perf_counter() - mark
        # Earlier completed results stay in place until this run finishes.
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        case.status = "RUNNING"
        case.error = None
        case.live_run_id = run_id
        session.commit()
        registry = load_registry(session)

        vehicles: dict[str, TrackedVehicle] = {}
        profiles: list[TrackProfile] = []
        span = 86.0 / len(clips)
        for clip_index, clip in enumerate(clips):
            base = 5 + span * clip_index
            label = clip.camera_label
            path = Path(clip.stored_path)
            metadata = probe_video(path)
            estimated = max(min(int(metadata.duration_sec * settings.sample_fps), settings.max_frames_per_clip), 1)
            stats = SamplingStats()
            publish("tracking", base, f"{label}: detecting and tracking vehicles", clip_index=clip_index + 1,
                    clip_count=len(clips))

            def on_frame(count: int) -> None:
                checkpoint()
                if count % 5 == 0:
                    publish("tracking", base + span * 0.35 * min(count / estimated, 1.0),
                            f"{label}: tracked {count} of about {estimated} sampled frames", clip_index=clip_index + 1,
                            clip_count=len(clips), frames_done=count, frames_total=estimated)

            mark = time.perf_counter()
            raw_tracks = models.detector.track_clip(sample_frames(path, metadata, stats=stats), on_frame)
            stage_seconds["tracking"] += time.perf_counter() - mark
            checkpoint()
            publish("stitching", base + span * 0.35, f"{label}: merging fragments of {len(raw_tracks)} raw track(s)")
            mark = time.perf_counter()
            tracks, merges = _stitch_tracks(raw_tracks)
            stage_seconds["stitching"] += time.perf_counter() - mark
            clip.processing = {**stats.as_dict(), "raw_tracks": len(raw_tracks), "fragments_merged": merges,
                               "tracks": len(tracks), "dropped_short_or_clipped": len(raw_tracks) - merges - len(tracks)}
            digits_only = clip.plate_format == "non_latin_digits"
            mark = time.perf_counter()
            clip_vehicles: list[TrackedVehicle] = []
            with ThreadPoolExecutor(max_workers=models.reader.workers, thread_name_prefix="track") as pool:
                futures = {
                    pool.submit(_analyse_track, track, digits_only,
                                settings.artifact_dir / case.id / run_id / clip.id / f"track_{track.track_id}",
                                checkpoint): track
                    for track in tracks
                }
                try:
                    for done, future in enumerate(as_completed(futures), start=1):
                        analysis = future.result()
                        track = futures[future]
                        artifact_base = settings.artifact_dir / case.id / run_id / clip.id / f"track_{track.track_id}"
                        vehicle, profile = _persist_track(session, case, clip, analysis, registry, artifact_base, run_id)
                        vehicles[vehicle.id] = vehicle
                        clip_vehicles.append(vehicle)
                        profiles.append(profile)
                        track._heap.clear()  # Release frame crops as soon as evidence is stored.
                        if done % COMMIT_EVERY_TRACKS == 0 or done == len(tracks):
                            session.commit()
                        publish("recognition", base + span * (0.4 + 0.6 * done / max(len(tracks), 1)),
                                f"{label}: analysed {done} of {len(tracks)} vehicle tracks",
                                clip_index=clip_index + 1, clip_count=len(clips),
                                tracks_done=len(vehicles), tracks_in_clip=len(tracks))
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise
            stage_seconds["recognition"] += time.perf_counter() - mark
            clip.processing = {**clip.processing, "repeated_plate_tracks": _flag_repeated_plates(clip_vehicles)}
            session.commit()

        checkpoint()
        publish("reid", 93, "Comparing tracks across cameras" if len(clips) > 1 else "One clip: skipping camera comparison")
        mark = time.perf_counter()
        entity_count, blocked_links = _build_entities(session, case, vehicles, profiles, registry, run_id)
        stage_seconds["reid"] += time.perf_counter() - mark
        session.add(AuditEvent(case_id=case.id, actor="system", action="EVIDENCE_VERIFIED",
                               note=f"All {len(clips)} clip hash(es) matched before analysis ({run_id})"))
        checkpoint()
        publish("report", 98, "Finalising case record")
        session.flush()
        session.execute(delete(TrackedVehicle).where(
            TrackedVehicle.case_id == case.id, or_(TrackedVehicle.run_id.is_(None), TrackedVehicle.run_id != run_id)))
        session.execute(delete(CrossCameraEntity).where(
            CrossCameraEntity.case_id == case.id,
            or_(CrossCameraEntity.run_id.is_(None), CrossCameraEntity.run_id != run_id)))
        case.active_run_id = run_id
        case.live_run_id = None
        case.pipeline_version = PIPELINE_VERSION
        case.status = "COMPLETED"
        case.runtime = {**models.status(), "elapsed_sec": round(time.perf_counter() - started, 2),
                        "vehicles": len(vehicles), "entities": entity_count, "links_blocked_by_plate": blocked_links,
                        "stage_seconds": {key: round(value, 1) for key, value in stage_seconds.items()},
                        "analysis_workers": models.reader.workers, "ocr_cache_hits": models.reader.cache_hits,
                        "registry_fingerprint": registry.fingerprint(), "run_id": run_id}
        session.add(AuditEvent(case_id=case.id, actor="system", action="ANALYSIS_COMPLETED",
                               note=f"{len(vehicles)} vehicle(s), {entity_count} possible cross-camera link(s), "
                                    f"pipeline {PIPELINE_VERSION}"))
        session.commit()
        progress_bus.publish(case_id, "done", 100,
                             f"Analysis complete: {len(vehicles)} vehicle(s), {entity_count} possible cross-camera link(s)",
                             "COMPLETED", tracks_done=len(vehicles))

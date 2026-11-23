"""Runs the forensic pipeline in a worker thread and publishes replayable progress."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import PIPELINE_VERSION, settings
from app.cv import attributes as attribute_module
from app.cv import make_model
from app.cv.clip_service import ClipService
from app.cv.detector_tracker import VehicleDetectorTracker, VehicleTrack, apply_stitching
from app.cv.device import active_device
from app.cv.plate_fusion import FusedPlate, PlateRead, fuse_plate_reads
from app.cv.plate_ocr import PlateObservation, PlateReader
from app.cv.reid import TrackProfile, link_tracks, mean_embedding, spatial_hsv_histogram
from app.cv.track_stitcher import plan_merges
from app.cv.video_processor import SamplingStats, probe_video, sample_frames
from app.db.database import SessionLocal
from app.db.models import AuditEvent, Case, Clip, CrossCameraEntity, RegistryVehicle, TrackedVehicle
from app.engine.matcher import RegistryIndex, match
from app.engine.schemas import LabelScore, MakeModelScore, PlateEvidence, QueryEvidence, RegistryRecord

logger = logging.getLogger(__name__)
KEYFRAMES_PER_TRACK = 5
MAX_PLATE_MISSES = 6
MIN_FRAMES_IF_TRUNCATED = 8
TERMINAL = {"COMPLETED", "FAILED"}


class ProgressBus:
    """Keeps each case's events so a late or reconnecting SSE client can replay them."""

    def __init__(self) -> None:
        self._events: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def reset(self, case_id: str) -> None:
        with self._lock:
            self._events[case_id] = []

    def publish(self, case_id: str, stage: str, percent: float, message: str, status: str = "RUNNING") -> None:
        event = {"stage": stage, "percent": round(percent, 1), "message": message, "status": status,
                 "ts": time.time()}
        with self._lock:
            events = self._events.setdefault(case_id, [])
            event["seq"] = len(events)
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
                try:
                    self.detector = VehicleDetectorTracker()
                    self.detector_error = None
                except Exception as error:
                    self.detector_error = f"{type(error).__name__}: {error}"
                    raise RuntimeError(f"Vehicle detector could not be loaded: {self.detector_error}") from error
            if self.reader is None:
                self.reader = PlateReader()
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
        }


models = ModelHub()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
_active: set[str] = set()
_active_lock = threading.Lock()


def submit_case(case_id: str) -> bool:
    with _active_lock:
        if case_id in _active:
            return False
        _active.add(case_id)
    progress_bus.reset(case_id)
    progress_bus.publish(case_id, "queued", 0, "Queued for analysis")
    _executor.submit(_run_guarded, case_id)
    return True


def is_running(case_id: str) -> bool:
    with _active_lock:
        return case_id in _active


def _run_guarded(case_id: str) -> None:
    try:
        run_pipeline(case_id)
    except Exception as error:
        logger.exception("Pipeline failed for case %s", case_id)
        with SessionLocal() as session:
            case = session.get(Case, case_id)
            if case:
                case.status = "FAILED"
                case.error = f"{type(error).__name__}: {error}"
                session.commit()
        progress_bus.publish(case_id, "failed", 100, f"Analysis failed: {error}", "FAILED")
    finally:
        with _active_lock:
            _active.discard(case_id)


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


def build_query(plate: PlateEvidence, attrs: dict) -> QueryEvidence:
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


def _write_image(path: Path, image: np.ndarray, quality: int = 90) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return path.relative_to(settings.artifact_dir).as_posix()


def _analyse_track(track: VehicleTrack, digits_only: bool = False) -> TrackAnalysis:
    observations = track.observations
    plate_results: list[PlateObservation] = []
    boxes_by_frame: dict[int, tuple[int, int, int, int]] = {}
    misses = 0
    for item in observations:
        result = models.reader.read_vehicle(item.crop, item.frame_idx, item.timestamp_sec, item.target_in_crop,
                                            item.occluders_in_crop)
        if result is None:
            misses += 1
            if not plate_results and misses >= MAX_PLATE_MISSES:
                break  # The best views show no plate, so weaker views will not help.
            continue
        plate_results.append(result)
        boxes_by_frame[item.frame_idx] = result.bbox_in_crop
    reads = [result.read for result in plate_results]
    stacked_read, stacked = models.reader.read_stack(plate_results)
    if stacked_read is not None:
        reads.append(stacked_read)
    fused = fuse_plate_reads(reads, digits_only=digits_only)

    crops = [item.crop for item in observations[:5]]
    boxes = [boxes_by_frame.get(item.frame_idx) for item in observations[:5]]
    scenes = [cv2.imdecode(np.frombuffer(item.frame_jpeg, np.uint8), cv2.IMREAD_COLOR) for item in observations[:5]]
    colours = attribute_module.estimate_colour(crops, boxes, scenes)
    embeddings = models.clip.encode_images(crops) if models.clip.available and crops else None
    embedding = mean_embedding(embeddings)
    body = attribute_module.classify_body(track.yolo_class, track.yolo_confidence, embedding, models.clip)
    make = make_model.recognise(embedding, body["label"], models.clip)
    attrs = {"colours": colours, "body_type": body, "make_model": make, "yolo_class": track.yolo_class}
    return TrackAnalysis(track, plate_results, fused, attrs, embeddings, spatial_hsv_histogram(crops), crops, stacked)


def _stitch_tracks(tracks: list[VehicleTrack]) -> tuple[list[VehicleTrack], int]:
    """Merge identity switches, then drop tracks too short or too clipped to be evidence."""
    vectors: dict[int, np.ndarray] = {}
    for track in tracks:
        crops = [item.crop for item in track.observations[:3]]
        if models.clip.available and crops:
            vectors[track.track_id] = mean_embedding(models.clip.encode_images(crops))
        else:
            vectors[track.track_id] = spatial_hsv_histogram(crops)

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


def _persist_track(session: Session, case: Case, clip: Clip, analysis: TrackAnalysis,
                   registry: RegistryIndex) -> tuple[TrackedVehicle, TrackProfile]:
    track = analysis.track
    vehicle = TrackedVehicle(case_id=case.id, clip_id=clip.id, track_id=track.track_id,
                             first_seen_sec=round(track.first_seen_sec, 3),
                             last_seen_sec=round(track.last_seen_sec, 3), frames_tracked=track.frames_tracked)
    session.add(vehicle)
    session.flush()
    base = settings.artifact_dir / case.id / clip.id / f"track_{track.track_id}"
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
            "bbox": list(item.bbox),
            "frame": _write_image(base / f"frame_{index}.jpg", frame, 82),
            "crop": _write_image(base / f"crop_{index}.jpg", item.crop),
        }
        plate = by_frame.get(item.frame_idx)
        if plate:
            entry.update({
                "plate_raw": _write_image(base / f"plate_raw_{index}.jpg", plate.raw_crop, 95),
                "plate_enhanced": _write_image(base / f"plate_enh_{index}.jpg", plate.enhanced_crop, 95),
                "plate_text": plate.read.raw_text,
                "plate_quality": round(plate.quality, 3),
                "ocr_source": plate.read.source,
            })
        keyframes.append(entry)

    evidence = analysis.fused.to_evidence()
    query = build_query(evidence, analysis.attributes)
    vehicle.best_crop = keyframes[0]["crop"] if keyframes else None
    vehicle.keyframes = keyframes
    vehicle.plate_reads = [_read_dict(obs.read) for obs in analysis.observations]
    vehicle.fused_plate = {
        **analysis.fused.to_dict(),
        "stack_crop": _write_image(base / "plate_stack.jpg", analysis.stacked_plate, 95)
        if analysis.stacked_plate is not None else None,
    }
    vehicle.attributes = {
        **analysis.attributes,
        "partial_view": track.mostly_truncated,
        "merged_track_ids": track.merged_track_ids,
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
    )
    return vehicle, profile


def _read_dict(read: PlateRead) -> dict:
    return {"frame_idx": read.frame_idx, "timestamp_sec": round(read.timestamp_sec, 3), "raw_text": read.raw_text,
            "char_confidences": [round(v, 4) for v in read.char_confidences],
            "sharpness_score": round(read.sharpness_score, 3), "bbox_area": read.bbox_area,
            "ocr_engine_score": round(read.ocr_engine_score, 4), "source": read.source, "derived": read.derived}


def _read_from_dict(item: dict) -> PlateRead:
    return PlateRead(item["frame_idx"], item["timestamp_sec"], item["raw_text"], item["char_confidences"],
                     item["sharpness_score"], item["bbox_area"], item["ocr_engine_score"], item.get("source", ""),
                     item.get("derived", False))


def _build_entities(session: Session, case: Case, vehicles: dict[str, TrackedVehicle],
                    profiles: list[TrackProfile], registry: RegistryIndex) -> tuple[int, int]:
    groups, links, blocked = link_tracks(profiles)
    tier_order = ["visual_time", "partial_plate", "strong_plate"]
    for group in groups:
        members = [vehicles[vehicle_id] for vehicle_id in group]
        merged_reads: list[PlateRead] = []
        for member in members:
            merged_reads.extend(_read_from_dict(item) for item in member.plate_reads)
        fused = fuse_plate_reads(merged_reads, digits_only=any(m.clip.plate_script == "non_latin" for m in members))
        best = max(members, key=lambda v: v.frames_tracked)
        query = build_query(fused.to_evidence(), best.attributes)
        timeline = []
        for member in members:
            clip = member.clip
            absolute = None
            if clip.recorded_at:
                recorded = clip.recorded_at if clip.recorded_at.tzinfo else clip.recorded_at.replace(tzinfo=timezone.utc)
                absolute = (recorded + timedelta(seconds=member.first_seen_sec)).isoformat()
            timeline.append({
                "vehicle_id": member.id, "clip_id": clip.id, "camera_label": clip.camera_label,
                "location": clip.location, "first_seen_sec": member.first_seen_sec,
                "last_seen_sec": member.last_seen_sec, "absolute_time": absolute,
                "plate": member.fused_plate.get("text", ""), "best_crop": member.best_crop,
            })
        timeline.sort(key=lambda t: (t["absolute_time"] is None, t["absolute_time"] or "", t["first_seen_sec"]))
        group_links = [link for link in links if link["a"] in group and link["b"] in group]
        entity = CrossCameraEntity(
            case_id=case.id, fused_plate=fused.to_dict(), timeline=timeline, links=group_links,
            match_result=match(query, registry).model_dump(), review_status="proposed",
            evidence_tier=min((link["evidence_tier"] for link in group_links), key=tier_order.index),
        )
        session.add(entity)
        session.flush()
        for member in members:
            member.entity_id = entity.id
    return len(groups), blocked


def refresh_legacy_results(session: Session) -> int:
    """Re-score stored results from older releases so outdated verdicts are never displayed."""
    registry = load_registry(session)
    updated = 0
    for vehicle in session.scalars(select(TrackedVehicle)).all():
        if "outcome" in (vehicle.match_result or {}) or not vehicle.active_evidence:
            continue
        vehicle.match_result = match(QueryEvidence.model_validate(vehicle.active_evidence), registry).model_dump()
        updated += 1
    for entity in session.scalars(select(CrossCameraEntity)).all():
        if "outcome" in (entity.match_result or {}) or not entity.vehicles:
            continue
        best = max(entity.vehicles, key=lambda v: v.frames_tracked)
        plate = PlateEvidence.from_text(entity.fused_plate.get("text", ""), 0.8)
        entity.match_result = match(build_query(plate, best.attributes), registry).model_dump()
        entity.review_status = "proposed"
        entity.evidence_tier = "legacy_unverified"
        updated += 1
    session.commit()
    return updated


def run_pipeline(case_id: str) -> None:
    publish = lambda stage, pct, msg: progress_bus.publish(case_id, stage, pct, msg)  # noqa: E731
    publish("models", 2, "Loading computer vision models")
    models.load()
    started = time.perf_counter()

    with SessionLocal() as session:
        case = session.get(Case, case_id)
        if case is None:
            raise ValueError("Case not found")
        clips = list(case.clips)
        if not clips:
            raise ValueError("Case has no clips")
        case.status = "RUNNING"
        case.error = None
        case.pipeline_version = PIPELINE_VERSION
        case.runtime = models.status()
        session.execute(delete(TrackedVehicle).where(TrackedVehicle.case_id == case.id))
        session.execute(delete(CrossCameraEntity).where(CrossCameraEntity.case_id == case.id))
        session.commit()
        session.expire_all()
        shutil.rmtree(settings.artifact_dir / case.id, ignore_errors=True)
        registry = load_registry(session)
        clips = list(session.get(Case, case_id).clips)

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
            publish("tracking", base, f"{label}: detecting and tracking vehicles")

            def on_frame(count: int) -> None:
                if count % 5 == 0:
                    publish("tracking", base + span * 0.5 * min(count / estimated, 1.0),
                            f"{label}: tracked {count} of about {estimated} sampled frames")

            raw_tracks = models.detector.track_clip(sample_frames(path, metadata, stats=stats), on_frame)
            publish("tracking", base + span * 0.5, f"{label}: merging duplicate tracks")
            tracks, merges = _stitch_tracks(raw_tracks)
            clip.processing = {**stats.as_dict(), "raw_tracks": len(raw_tracks), "fragments_merged": merges,
                               "tracks": len(tracks)}
            for track_index, track in enumerate(tracks):
                publish("recognition", base + span * (0.5 + 0.5 * track_index / max(len(tracks), 1)),
                        f"{label}: reading plate and attributes for vehicle {track_index + 1} of {len(tracks)}")
                analysis = _analyse_track(track, digits_only=clip.plate_script == "non_latin")
                vehicle, profile = _persist_track(session, case, clip, analysis, registry)
                vehicles[vehicle.id] = vehicle
                profiles.append(profile)
            session.commit()

        publish("reid", 93, "Linking vehicles across cameras")
        entity_count, blocked_links = _build_entities(session, case, vehicles, profiles, registry)
        publish("report", 98, "Finalising case record")
        case.status = "COMPLETED"
        case.runtime = {**models.status(), "elapsed_sec": round(time.perf_counter() - started, 2),
                        "vehicles": len(vehicles), "entities": entity_count, "links_blocked_by_plate": blocked_links}
        session.add(AuditEvent(case_id=case.id, actor="system", action="ANALYSIS_COMPLETED",
                               note=f"{len(vehicles)} vehicle(s), {entity_count} possible cross-camera link(s), "
                                    f"pipeline {PIPELINE_VERSION}"))
        session.commit()
        progress_bus.publish(case_id, "done", 100,
                             f"Analysis complete: {len(vehicles)} vehicle(s), {entity_count} possible cross-camera link(s)",
                             "COMPLETED")

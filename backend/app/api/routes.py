from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import PIPELINE_VERSION, settings
from app.cv.model_assets import asset_status
from app.cv.video_processor import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    extract_image_sequence,
    probe_video,
    sha256_file,
)
from app.db.database import get_db
from app.db.models import AuditEvent, Case, Clip, CrossCameraEntity, RegistryVehicle, TrackedVehicle
from app.engine.confusion_matrices import (
    BODY_TYPES,
    COLOURS,
    PLATE_FORMAT_NAMES,
    PLATE_FORMAT_OPTIONS,
    normalise_body,
)
from app.engine.matcher import match
from app.engine.schemas import (
    CharCandidate,
    LabelScore,
    MakeModelScore,
    PlateEvidence,
    QueryEvidence,
    RegistryRecord,
    SlotEvidence,
)
from app.api.labels import OUTCOME_LABELS
from app.reports.generator import render_html, render_pdf
from app.services.case_summary import build_preflight, readability, registry_snapshot, summarise
from app.services.pipeline_orchestrator import (
    invalidate_registry,
    is_running,
    load_registry,
    models,
    progress_bus,
    request_cancel,
    rescore_case,
    submit_case,
)

router = APIRouter(prefix="/api")
_PLATE = re.compile(r"^[A-Z0-9]{4,12}$")
MAX_REGISTRY_ROWS = 50_000


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def clip_dict(clip: Clip) -> dict:
    return {
        "id": clip.id, "filename": clip.filename, "sha256": clip.sha256, "size_bytes": clip.size_bytes,
        "camera_label": clip.camera_label, "location": clip.location, "recorded_at": _iso(clip.recorded_at),
        "ingested_at": _iso(clip.ingested_at), "fps": clip.fps, "width": clip.width, "height": clip.height,
        "duration_sec": clip.duration_sec, "frame_count": clip.frame_count, "codec": clip.codec,
        "plate_script": clip.plate_script, "plate_format": clip.plate_format, "timezone": clip.timezone,
        "latitude": clip.latitude, "longitude": clip.longitude, "synthetic": clip.filename.startswith("synthetic_"),
        "processing": clip.processing,
    }


def vehicle_summary(vehicle: TrackedVehicle) -> dict:
    result = vehicle.match_result or {}
    lead = (result.get("candidates") or [None])[0]
    closest = (result.get("rejected_candidates") or [None])[0]
    return {
        "id": vehicle.id, "clip_id": vehicle.clip_id, "camera_label": vehicle.clip.camera_label,
        "entity_id": vehicle.entity_id, "track_id": vehicle.track_id, "first_seen_sec": vehicle.first_seen_sec,
        "last_seen_sec": vehicle.last_seen_sec, "frames_tracked": vehicle.frames_tracked,
        "best_crop": vehicle.best_crop, "plate": result.get("query_plate", ""),
        "known_chars": result.get("known_chars", 0), "attributes": vehicle.attributes,
        "status": result.get("status"), "outcome": result.get("outcome"),
        "reason_codes": result.get("reason_codes", []), "diagnostics": result.get("diagnostics", []),
        "top_plate": lead["vehicle"]["plate"] if lead else None, "top_score": lead["score"] if lead else None,
        "closest_plate": closest["vehicle"]["plate"] if closest else None,
        "overridden": bool(vehicle.overrides),
        "link_status": vehicle.entity.review_status if vehicle.entity else None,
        "plate_script": vehicle.clip.plate_script,
        "plate_format": vehicle.clip.plate_format,
        "readability": readability(result.get("known_chars", 0)),
        "registry_coverage": result.get("registry_coverage"),
        "track_quality": (vehicle.attributes or {}).get("track_quality"),
    }


def entity_dict(entity: CrossCameraEntity) -> dict:
    return {"id": entity.id, "fused_plate": entity.fused_plate, "timeline": entity.timeline,
            "links": entity.links, "match_result": entity.match_result, "review_status": entity.review_status,
            "evidence_tier": entity.evidence_tier, "reviewed_by": entity.reviewed_by,
            "reviewed_at": _iso(entity.reviewed_at), "review_note": entity.review_note}


def audit_dict(event: AuditEvent) -> dict:
    return {"id": event.id, "vehicle_id": event.vehicle_id, "actor": event.actor, "action": event.action,
            "field": event.field, "ai_extracted": event.ai_extracted,
            "investigator_verified": event.investigator_verified, "note": event.note,
            "created_at": _iso(event.created_at)}


def case_summary(session: Session, case: Case) -> dict:
    return summarise(case.display_vehicles, case.display_entities, case.clips, load_registry(session), case.runtime)


def case_dict(case: Case, detail: bool = False, session: Session | None = None) -> dict:
    vehicles = case.display_vehicles
    payload = {
        "id": case.id, "title": case.title, "description": case.description, "status": case.status,
        "error": case.error, "pipeline_version": case.pipeline_version, "created_at": _iso(case.created_at),
        "updated_at": _iso(case.updated_at), "clip_count": len(case.clips), "vehicle_count": len(vehicles),
        "running": is_running(case.id),
        "stale": bool(case.completed_vehicles) and case.pipeline_version != PIPELINE_VERSION,
        "has_completed_run": bool(case.completed_vehicles) or (case.status == "COMPLETED"),
        "showing_live_run": bool(case.live_run_id),
    }
    if detail:
        payload.update(runtime=case.runtime, summary=case_summary(session, case),
                       preflight=build_preflight(case, load_registry(session)),
                       clips=[clip_dict(c) for c in case.clips],
                       entities=[entity_dict(e) for e in case.display_entities],
                       audit=[audit_dict(e) for e in case.audit_events])
    return payload


def _case_or_404(session: Session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


def _vehicle_or_404(session: Session, case_id: str, vehicle_id: str) -> TrackedVehicle:
    vehicle = session.get(TrackedVehicle, vehicle_id)
    if vehicle is None or vehicle.case_id != case_id:
        raise HTTPException(404, "Vehicle not found")
    return vehicle


@router.get("/health")
def health(session: Session = Depends(get_db)) -> dict:
    return {
        "status": "ok", "pipeline_version": PIPELINE_VERSION,
        "registry_count": session.scalar(select(func.count()).select_from(RegistryVehicle)),
        "synthetic_count": session.scalar(select(func.count()).select_from(RegistryVehicle)
                                          .where(RegistryVehicle.source == "synthetic")),
        "models": models.status(),
    }


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)


@router.post("/cases", status_code=201)
def create_case(body: CaseCreate, session: Session = Depends(get_db)) -> dict:
    case = Case(title=body.title.strip(), description=body.description)
    session.add(case)
    session.flush()
    session.add(AuditEvent(case_id=case.id, actor="system", action="CASE_CREATED", note=case.title))
    session.commit()
    return case_dict(case, detail=True, session=session)


@router.get("/cases")
def list_cases(session: Session = Depends(get_db)) -> list[dict]:
    return [case_dict(c) for c in session.scalars(select(Case).order_by(Case.created_at.desc())).all()]


@router.get("/cases/{case_id}")
def get_case(case_id: str, session: Session = Depends(get_db)) -> dict:
    return case_dict(_case_or_404(session, case_id), detail=True, session=session)


def _zone(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise HTTPException(422, f"Unknown timezone: {value}") from error
    return value


def _parse_time(value: str | None, zone: str | None = None) -> datetime | None:
    """Store capture time in UTC. A naive time is interpreted in the camera's timezone."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(422, f"Invalid recorded_at: {value}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(zone) if zone else timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coordinate(value: str | float | None, limit: float, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, f"Invalid {name}") from error
    if abs(number) > limit:
        raise HTTPException(422, f"{name} is out of range")
    return number


def _plate_format(value: str | None, script: str | None = None) -> str:
    if value:
        if value not in PLATE_FORMAT_OPTIONS:
            raise HTTPException(422, f"plate_format must be one of {', '.join(PLATE_FORMAT_OPTIONS)}")
        return value
    if script in (None, "", "latin"):
        return "latin_any"
    if script == "non_latin":
        return "non_latin_digits"
    raise HTTPException(422, "plate_script must be latin or non_latin")


def _script_for(plate_format: str) -> str:
    return "non_latin" if plate_format == "non_latin_digits" else "latin"


def _store_upload(upload: UploadFile, target: Path) -> int:
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    with target.open("wb") as handle:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"{upload.filename} exceeds {settings.max_upload_mb} MB")
            handle.write(chunk)
    return written


@router.post("/cases/{case_id}/clips", status_code=201)
def upload_clips(
    case_id: str,
    files: list[UploadFile] = File(...),
    camera_label: list[str] = Form(default=[]),
    location: list[str] = Form(default=[]),
    recorded_at: list[str] = Form(default=[]),
    plate_script: list[str] = Form(default=[]),
    plate_format: list[str] = Form(default=[]),
    timezone_name: list[str] = Form(default=[], alias="timezone"),
    latitude: list[str] = Form(default=[]),
    longitude: list[str] = Form(default=[]),
    session: Session = Depends(get_db),
) -> dict:
    case = _case_or_404(session, case_id)
    if is_running(case_id):
        raise HTTPException(409, "Analysis is running")
    directory = settings.upload_dir / case_id
    directory.mkdir(parents=True, exist_ok=True)
    created: list[Clip] = []
    for index, upload in enumerate(files):
        name = Path(upload.filename or "clip").name
        suffix = Path(name).suffix.lower()
        if suffix not in VIDEO_EXTENSIONS | {".zip"}:
            raise HTTPException(415, f"Unsupported file type: {name}")
        token = uuid.uuid4().hex[:12]
        stored = directory / f"{token}{suffix}"
        size = _store_upload(upload, stored)
        digest = sha256_file(stored)
        os.chmod(stored, 0o444)  # Original evidence is immutable once hashed.
        if any(existing.sha256 == digest for existing in case.clips):
            os.chmod(stored, 0o644)
            stored.unlink(missing_ok=True)
            raise HTTPException(409, f"{name} is already in this case (identical SHA-256)")
        media = stored
        try:
            if suffix == ".zip":
                media = extract_image_sequence(stored, directory / token)
            metadata = probe_video(media)
        except Exception as error:
            os.chmod(stored, 0o644)
            stored.unlink(missing_ok=True)
            if media != stored:
                shutil.rmtree(media, ignore_errors=True)
            raise HTTPException(422, f"Could not read {name}: {error}") from error
        label = camera_label[index].strip() if index < len(camera_label) and camera_label[index].strip() else \
            f"Camera {len(case.clips) + 1}"
        zone = _zone(timezone_name[index] if index < len(timezone_name) else None)
        chosen_format = _plate_format(plate_format[index] if index < len(plate_format) else None,
                                      plate_script[index] if index < len(plate_script) else None)
        clip = Clip(
            case_id=case.id, filename=name, stored_path=str(media), sha256=digest, size_bytes=size,
            camera_label=label, location=(location[index].strip() or None) if index < len(location) else None,
            recorded_at=_parse_time(recorded_at[index] if index < len(recorded_at) else None, zone),
            timezone=zone,
            latitude=_coordinate(latitude[index] if index < len(latitude) else None, 90, "latitude"),
            longitude=_coordinate(longitude[index] if index < len(longitude) else None, 180, "longitude"),
            plate_format=chosen_format,
            fps=metadata.fps, width=metadata.width, height=metadata.height, duration_sec=metadata.duration_sec,
            frame_count=metadata.frame_count, codec=metadata.codec,
            plate_script=_script_for(chosen_format),
        )
        case.clips.append(clip)
        session.flush()
        session.add(AuditEvent(case_id=case.id, actor="system", action="EVIDENCE_INGESTED", field="sha256",
                               ai_extracted=digest, note=f"{name} as {label}"))
        created.append(clip)
    case.status = "READY"
    session.commit()
    return {"clips": [clip_dict(c) for c in created], "case": case_dict(case)}


class ClipUpdate(BaseModel):
    camera_label: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    recorded_at: str | None = None
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    plate_script: str | None = None
    plate_format: str | None = None


@router.patch("/cases/{case_id}/clips/{clip_id}")
def update_clip(case_id: str, clip_id: str, body: ClipUpdate, session: Session = Depends(get_db)) -> dict:
    case = _case_or_404(session, case_id)
    if is_running(case_id):
        raise HTTPException(409, "Analysis is running")
    clip = session.get(Clip, clip_id)
    if clip is None or clip.case_id != case_id:
        raise HTTPException(404, "Clip not found")
    changes = body.model_dump(exclude_unset=True)
    if "camera_label" in changes and changes["camera_label"]:
        clip.camera_label = changes["camera_label"].strip()
    if "location" in changes:
        clip.location = (changes["location"] or "").strip() or None
    if "timezone" in changes:
        clip.timezone = _zone(changes["timezone"])
    if "recorded_at" in changes:
        clip.recorded_at = _parse_time(changes["recorded_at"], clip.timezone)
    if "latitude" in changes:
        clip.latitude = _coordinate(changes["latitude"], 90, "latitude")
    if "longitude" in changes:
        clip.longitude = _coordinate(changes["longitude"], 180, "longitude")
    if changes.get("plate_format") or changes.get("plate_script"):
        clip.plate_format = _plate_format(changes.get("plate_format"), changes.get("plate_script"))
        clip.plate_script = _script_for(clip.plate_format)
    session.add(AuditEvent(case_id=case.id, actor="Investigator", action="CLIP_METADATA_UPDATED", field=clip.camera_label,
                           note=", ".join(sorted(changes)) or "no change"))
    session.commit()
    return clip_dict(clip)


class AnalyzeRequest(BaseModel):
    acknowledge_no_coverage: bool = False


@router.get("/cases/{case_id}/preflight")
def case_preflight(case_id: str, session: Session = Depends(get_db)) -> dict:
    return build_preflight(_case_or_404(session, case_id), load_registry(session))


@router.post("/cases/{case_id}/analyze", status_code=202)
def analyze_case(case_id: str, body: AnalyzeRequest | None = None, session: Session = Depends(get_db)) -> dict:
    case = _case_or_404(session, case_id)
    if not case.clips:
        raise HTTPException(422, "Upload at least one clip first")
    assets = asset_status()
    if not assets["ready"]:
        raise HTTPException(503, f"Missing {', '.join(assets['missing'])}. From the backend folder, run: "
                                 f"{assets['install_command']}")
    preflight = build_preflight(case, load_registry(session))
    if preflight["requires_acknowledgement"] and not (body and body.acknowledge_no_coverage):
        raise HTTPException(409, {"code": "NO_REGISTRY_COVERAGE",
                                  "message": "The active registry has no records for this camera's plate format.",
                                  "preflight": preflight})
    if preflight["requires_acknowledgement"]:
        cameras = ", ".join(row["camera_label"] for row in preflight["coverage"] if row["status"] == "no_coverage")
        session.add(AuditEvent(case_id=case.id, actor="Investigator", action="NO_COVERAGE_ACKNOWLEDGED", field=cameras,
                               note="Analysis started for OCR evidence without a compatible registry."))
    if not submit_case(case_id):
        raise HTTPException(409, "Analysis is already running")
    case.status = "QUEUED"
    session.commit()
    return {"case_id": case_id, "status": "QUEUED"}


@router.post("/cases/{case_id}/cancel", status_code=202)
def cancel_case(case_id: str, session: Session = Depends(get_db)) -> dict:
    _case_or_404(session, case_id)
    if not request_cancel(case_id):
        raise HTTPException(409, "No analysis is running for this case")
    return {"case_id": case_id, "status": "CANCELLING"}


@router.post("/cases/{case_id}/rescore")
def rescore(case_id: str, session: Session = Depends(get_db)) -> dict:
    """Re-run registry matching on stored OCR evidence after the registry or plate format changes."""
    case = _case_or_404(session, case_id)
    if is_running(case_id):
        raise HTTPException(409, "Analysis is running")
    if not case.completed_vehicles:
        raise HTTPException(422, "Run analysis before re-matching")
    for vehicle in case.completed_vehicles:
        stored = (vehicle.ai_evidence or {}).get("plate_format", "latin_any")
        if (stored == "non_latin_digits") != (vehicle.clip.plate_format == "non_latin_digits"):
            raise HTTPException(409, f"{vehicle.clip.camera_label} changed to or from digits-only reading. "
                                     "Re-run analysis so its OCR evidence is rebuilt.")
    result = rescore_case(session, case)
    return {**result, "summary": case_summary(session, case)}


@router.get("/cases/{case_id}/progress")
async def case_progress(case_id: str, session: Session = Depends(get_db)) -> StreamingResponse:
    status = _case_or_404(session, case_id).status
    session.close()
    return StreamingResponse(progress_bus.stream(case_id, status), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/cases/{case_id}/vehicles")
def list_vehicles(case_id: str, session: Session = Depends(get_db)) -> dict:
    case = _case_or_404(session, case_id)
    ordered = sorted(case.display_vehicles, key=lambda v: (v.clip.camera_label, v.first_seen_sec))
    return {"vehicles": [vehicle_summary(v) for v in ordered],
            "entities": [entity_dict(e) for e in case.display_entities]}


def vehicle_detail(vehicle: TrackedVehicle) -> dict:
    return {
        **vehicle_summary(vehicle), "keyframes": vehicle.keyframes, "plate_reads": vehicle.plate_reads,
        "fused_plate": vehicle.fused_plate, "ai_evidence": vehicle.ai_evidence,
        "active_evidence": vehicle.active_evidence, "match_result": vehicle.match_result,
        "overrides": vehicle.overrides, "clip": clip_dict(vehicle.clip),
        "entity": entity_dict(vehicle.entity) if vehicle.entity else None,
    }


@router.get("/cases/{case_id}/vehicles/{vehicle_id}")
def get_vehicle(case_id: str, vehicle_id: str, session: Session = Depends(get_db)) -> dict:
    return vehicle_detail(_vehicle_or_404(session, case_id, vehicle_id))


class SlotOverride(BaseModel):
    position: int = Field(ge=0, le=15)
    char: str = Field(min_length=1, max_length=1)


class OverrideRequest(BaseModel):
    actor: str = Field(default="Investigator", min_length=1, max_length=120)
    slots: list[SlotOverride] = Field(default_factory=list)
    colour: str | None = None
    body_type: str | None = None
    note: str | None = Field(default=None, max_length=1000)
    reset: bool = False


@router.post("/cases/{case_id}/vehicles/{vehicle_id}/override")
def override_vehicle(case_id: str, vehicle_id: str, body: OverrideRequest, session: Session = Depends(get_db)) -> dict:
    vehicle = _vehicle_or_404(session, case_id, vehicle_id)
    evidence = QueryEvidence.model_validate(vehicle.ai_evidence if body.reset else vehicle.active_evidence)
    overrides = {} if body.reset else {**vehicle.overrides}
    events: list[AuditEvent] = []

    def log(field: str, before: str | None, after: str | None) -> None:
        events.append(AuditEvent(case_id=case_id, vehicle_id=vehicle.id, actor=body.actor, action="INVESTIGATOR_OVERRIDE",
                                 field=field, ai_extracted=before, investigator_verified=after, note=body.note))

    if body.reset:
        events.append(AuditEvent(case_id=case_id, vehicle_id=vehicle.id, actor=body.actor, action="OVERRIDE_RESET",
                                 note=body.note))
    ai_evidence = QueryEvidence.model_validate(vehicle.ai_evidence)
    slots = evidence.plate.slots
    for item in body.slots:
        char = item.char.upper()
        if not (char == "?" or (char.isascii() and char.isalnum())):
            raise HTTPException(422, f"Invalid plate character: {item.char}")
        while len(slots) <= item.position:
            slots.append(SlotEvidence())
        original = ai_evidence.plate.slots[item.position].char if item.position < len(ai_evidence.plate.slots) else "?"
        if char == "?":
            slots[item.position] = SlotEvidence()
            overrides.setdefault("slots", {}).pop(str(item.position), None)
        else:
            slots[item.position] = SlotEvidence(char=char, confidence=1.0, locked=True,
                                                candidates=[CharCandidate(char=char, probability=1.0)])
            overrides.setdefault("slots", {})[str(item.position)] = char
        log(f"plate_slot_{item.position + 1}", original, char)
    if body.colour:
        colour = body.colour.lower()
        if colour not in COLOURS:
            raise HTTPException(422, f"Unknown colour: {body.colour}")
        log("colour", ai_evidence.colours[0].label if ai_evidence.colours else None, colour)
        evidence.colours = [LabelScore(label=colour, confidence=1.0)]
        overrides["colour"] = colour
    if body.body_type:
        body_type = normalise_body(body.body_type)
        if body_type not in BODY_TYPES:
            raise HTTPException(422, f"Unknown body type: {body.body_type}")
        log("body_type", ai_evidence.body_type, body_type)
        evidence.body_type, evidence.body_confidence = body_type, 1.0
        overrides["body_type"] = body_type
    if overrides.get("slots") == {}:
        overrides.pop("slots")

    result = match(evidence, load_registry(session))
    vehicle.active_evidence = evidence.model_dump()
    vehicle.match_result = result.model_dump()
    vehicle.overrides = overrides
    session.add_all(events)
    session.commit()
    return {"vehicle": vehicle_detail(vehicle), "rerank_ms": result.elapsed_ms,
            "audit": [audit_dict(e) for e in vehicle.case.audit_events]}


class EntityReview(BaseModel):
    decision: Literal["confirmed", "rejected", "proposed"]
    actor: str = Field(default="Investigator", min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=1000)


@router.post("/cases/{case_id}/entities/{entity_id}/review")
def review_entity(case_id: str, entity_id: str, body: EntityReview, session: Session = Depends(get_db)) -> dict:
    entity = session.get(CrossCameraEntity, entity_id)
    if entity is None or entity.case_id != case_id:
        raise HTTPException(404, "Link not found")
    previous = entity.review_status
    entity.review_status = body.decision
    entity.reviewed_by = None if body.decision == "proposed" else body.actor
    entity.reviewed_at = None if body.decision == "proposed" else datetime.now(timezone.utc)
    entity.review_note = body.note
    session.add(AuditEvent(case_id=case_id, actor=body.actor, action="LINK_REVIEWED", field=f"link {entity.id}",
                           ai_extracted=previous, investigator_verified=body.decision, note=body.note))
    session.commit()
    return entity_dict(entity)


def _report_scope(session: Session, case_id: str, clip_id: str | None) -> None:
    case = _case_or_404(session, case_id)
    if clip_id and not any(clip.id == clip_id for clip in case.clips):
        raise HTTPException(404, "Clip not found in this case")


@router.get("/cases/{case_id}/report/html", response_class=HTMLResponse)
def report_html(case_id: str, download: bool = False, clip_id: str | None = None,
                session: Session = Depends(get_db)) -> HTMLResponse:
    _report_scope(session, case_id, clip_id)
    headers = {"Content-Disposition": f'attachment; filename="forensic_report_{case_id}.html"'} if download else {}
    return HTMLResponse(render_html(session, case_id, clip_id=clip_id), headers=headers)


@router.get("/cases/{case_id}/report/pdf")
def report_pdf(case_id: str, appendix: bool = False, clip_id: str | None = None,
               session: Session = Depends(get_db)) -> Response:
    _report_scope(session, case_id, clip_id)
    data, engine = render_pdf(session, case_id, appendix, clip_id)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="forensic_report_{case_id}.pdf"',
        "X-PDF-Engine": engine,
    })


EXPORT_FIELDS = [
    "case_id", "clip_id", "camera", "clip_sha256", "plate_format", "track_id", "first_seen_sec", "last_seen_sec",
    "duration_sec", "sampled_frames", "track_quality", "quality_reasons", "plate_read", "known_characters",
    "readability", "outcome", "outcome_label", "reason_codes", "registry_searched", "compatible_records",
    "top_registry_plate", "match_score_uncalibrated", "registry_record_source", "link_status", "best_plate_crop_sha256",
]


def _spreadsheet_safe(value):
    """Stop user-supplied text from being executed as a spreadsheet formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _export_rows(case: Case, clip_id: str | None) -> list[dict]:
    rows = []
    vehicles = [v for v in case.completed_vehicles if clip_id is None or v.clip_id == clip_id]
    for vehicle in sorted(vehicles, key=lambda v: (v.clip.camera_label, v.first_seen_sec, v.track_id)):
        result = vehicle.match_result or {}
        coverage = result.get("registry_coverage") or {}
        lead = (result.get("candidates") or [None])[0]
        quality = (vehicle.attributes or {}).get("track_quality") or {}
        hashes = [frame.get("crop_sha256") for frame in vehicle.keyframes or [] if frame.get("crop_sha256")]
        rows.append({
            "case_id": case.id, "clip_id": vehicle.clip_id, "camera": vehicle.clip.camera_label,
            "clip_sha256": vehicle.clip.sha256, "plate_format": vehicle.clip.plate_format, "track_id": vehicle.track_id,
            "first_seen_sec": vehicle.first_seen_sec, "last_seen_sec": vehicle.last_seen_sec,
            "duration_sec": round(vehicle.last_seen_sec - vehicle.first_seen_sec, 2),
            "sampled_frames": vehicle.frames_tracked, "track_quality": quality.get("tier", "not_assessed"),
            "quality_reasons": "; ".join(quality.get("reasons", [])), "plate_read": result.get("query_plate", ""),
            "known_characters": result.get("known_chars", 0), "readability": readability(result.get("known_chars", 0)),
            "outcome": result.get("outcome"), "outcome_label": OUTCOME_LABELS.get(result.get("outcome", ""), ""),
            "reason_codes": ";".join(result.get("reason_codes", [])), "registry_searched": coverage.get("searched"),
            "compatible_records": coverage.get("compatible_records"),
            "top_registry_plate": lead["vehicle"]["plate"] if lead else "",
            "match_score_uncalibrated": lead["score"] if lead else "",
            "registry_record_source": lead["vehicle"].get("source", "") if lead else "",
            "link_status": vehicle.entity.review_status if vehicle.entity else "",
            "best_plate_crop_sha256": hashes[0] if hashes else "",
        })
    return rows


@router.get("/cases/{case_id}/export.csv")
def export_csv(case_id: str, clip_id: str | None = None, session: Session = Depends(get_db)) -> Response:
    _report_scope(session, case_id, clip_id)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for row in _export_rows(session.get(Case, case_id), clip_id):
        writer.writerow({key: _spreadsheet_safe(value) for key, value in row.items()})
    return Response(buffer.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="vitra_{case_id}.csv"'})


@router.get("/cases/{case_id}/export.json")
def export_json(case_id: str, clip_id: str | None = None, session: Session = Depends(get_db)) -> JSONResponse:
    _report_scope(session, case_id, clip_id)
    case = session.get(Case, case_id)
    clips = [c for c in case.clips if clip_id is None or c.id == clip_id]
    vehicles = [v for v in case.completed_vehicles if clip_id is None or v.clip_id == clip_id]
    entities = [e for e in case.completed_entities
                if clip_id is None or any(stop["clip_id"] == clip_id for stop in e.timeline)]
    fused = {(v.clip_id, v.track_id): v.fused_plate for v in vehicles}
    tracks = [{**row, "characters": [
        {"position": s["position"], "char": s["char"], "confidence": s["confidence"],
         "alternatives": s.get("candidates", []), "unknown_reason": s.get("unknown_reason")}
        for s in fused[(row["clip_id"], row["track_id"])].get("slots", [])
    ], "rejected_reads": fused[(row["clip_id"], row["track_id"])].get("rejected_reads", [])}
        for row in _export_rows(case, clip_id)]
    payload = {
        "case": {"id": case.id, "title": case.title, "status": case.status, "pipeline_version": case.pipeline_version},
        "summary": summarise(vehicles, entities, clips, load_registry(session), case.runtime),
        "clips": [clip_dict(c) for c in clips], "tracks": tracks, "audit": [audit_dict(e) for e in case.audit_events],
    }
    return JSONResponse(payload, headers={
        "Content-Disposition": f'attachment; filename="vitra_{case_id}.json"'})


def registry_dict(row: RegistryVehicle) -> dict:
    return {"id": row.id, "plate": row.plate, "make": row.make, "model": row.model, "body_type": row.body_type,
            "colour": row.colour, "year": row.year, "owner_name": row.owner_name, "owner_city": row.owner_city,
            "status": row.status, "source": row.source}


@router.get("/registry/coverage")
def registry_coverage(session: Session = Depends(get_db)) -> dict:
    index = load_registry(session)
    return {**registry_snapshot(index), "formats": [
        {"plate_format": key, "label": PLATE_FORMAT_NAMES[key], "compatible_records": index.compatible_count(key)}
        for key in PLATE_FORMAT_OPTIONS
    ]}


@router.get("/registry")
def search_registry(
    q: str = "", status: str | None = None, body_type: str | None = None, colour: str | None = None,
    source: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), session: Session = Depends(get_db),
) -> dict:
    query = select(RegistryVehicle)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        query = query.where(or_(RegistryVehicle.plate.ilike(like, escape="\\"), RegistryVehicle.make.ilike(like, escape="\\"),
                                RegistryVehicle.model.ilike(like, escape="\\"),
                                RegistryVehicle.owner_name.ilike(like, escape="\\")))
    if status:
        query = query.where(RegistryVehicle.status == status)
    if body_type:
        query = query.where(RegistryVehicle.body_type == body_type)
    if colour:
        query = query.where(RegistryVehicle.colour == colour)
    if source:
        query = query.where(RegistryVehicle.source == source)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(RegistryVehicle.plate).offset((page - 1) * page_size).limit(page_size)).all()
    synthetic = session.scalar(select(func.count()).select_from(RegistryVehicle)
                               .where(RegistryVehicle.source == "synthetic")) or 0
    registry_total = session.scalar(select(func.count()).select_from(RegistryVehicle)) or 0
    return {"items": [registry_dict(r) for r in rows], "total": total, "page": page, "page_size": page_size,
            "registry_total": registry_total, "synthetic_count": synthetic}


def _parse_registry(name: str, raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig")
    if name.lower().endswith(".json"):
        data = json.loads(text)
        data = data.get("vehicles", data) if isinstance(data, dict) else data
        if not isinstance(data, list):
            raise ValueError("JSON must be an array or an object with a 'vehicles' array")
        return data
    return list(csv.DictReader(io.StringIO(text)))


@router.post("/registry/upload")
def upload_registry(
    file: UploadFile = File(...), mode: str = Form("merge"), session: Session = Depends(get_db),
) -> dict:
    if mode not in {"merge", "replace"}:
        raise HTTPException(422, "mode must be merge or replace")
    name = file.filename or ""
    if not name.lower().endswith((".csv", ".json")):
        raise HTTPException(415, "Registry must be CSV or JSON")
    try:
        rows = _parse_registry(name, file.file.read())
    except (ValueError, UnicodeDecodeError, csv.Error) as error:
        raise HTTPException(422, f"Could not parse registry: {error}") from error
    if len(rows) > MAX_REGISTRY_ROWS:
        raise HTTPException(413, f"Registry exceeds {MAX_REGISTRY_ROWS} rows")
    valid: dict[str, dict] = {}
    errors: list[str] = []
    for line, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"Row {line}: not an object")
            continue
        normal = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
        plate = re.sub(r"[^A-Z0-9]", "", str(normal.get("plate") or normal.get("registration") or "").upper())
        if not _PLATE.match(plate):
            errors.append(f"Row {line}: invalid plate")
            continue
        body = normalise_body(str(normal.get("body_type") or normal.get("type") or "sedan"))
        colour = str(normal.get("colour") or normal.get("color") or "white").lower()
        if body not in BODY_TYPES:
            errors.append(f"Row {line}: unknown body type {body}")
            continue
        if colour not in COLOURS:
            errors.append(f"Row {line}: unknown colour {colour}")
            continue
        try:
            year = int(normal["year"]) if normal.get("year") not in (None, "") else None
        except (TypeError, ValueError):
            errors.append(f"Row {line}: invalid year")
            continue
        status = str(normal.get("status") or "ACTIVE").upper()
        if status not in {"ACTIVE", "STOLEN_ALERT", "EXPIRED"}:
            errors.append(f"Row {line}: invalid status {status}")
            continue
        valid[plate] = {"plate": plate, "make": str(normal.get("make") or "Unknown"),
                        "model": str(normal.get("model") or "Unknown"), "body_type": body, "colour": colour,
                        "year": year, "owner_name": normal.get("owner_name") or normal.get("owner"),
                        "owner_city": normal.get("owner_city") or normal.get("city"), "status": status,
                        "source": "uploaded"}
    if not valid:
        raise HTTPException(422, {"message": "No valid rows", "errors": errors[:20]})
    if mode == "replace":
        session.query(RegistryVehicle).delete()
        session.flush()
        existing: dict[str, RegistryVehicle] = {}
    else:
        existing = {r.plate: r for r in session.scalars(
            select(RegistryVehicle).where(RegistryVehicle.plate.in_(list(valid)))).all()}
    inserted = updated = 0
    for plate, values in valid.items():
        if plate in existing:
            for key, value in values.items():
                setattr(existing[plate], key, value)
            updated += 1
        else:
            session.add(RegistryVehicle(**values))
            inserted += 1
    session.commit()
    invalidate_registry()
    total = session.scalar(select(func.count()).select_from(RegistryVehicle))
    return {"inserted": inserted, "updated": updated, "rejected": len(rows) - len(valid), "errors": errors[:20],
            "total": total, "coverage": registry_snapshot(load_registry(session))["by_family"]}


class MatchTest(BaseModel):
    plate: str = Field(default="", max_length=16)
    plate_confidence: float = Field(default=0.9, ge=0.01, le=1.0)
    plate_format: str = "latin_any"
    anchor: str | None = None
    colour: str | None = None
    secondary_colour: str | None = None
    body_type: str | None = None
    body_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    make: str | None = None
    model: str | None = None
    make_model_confidence: float = Field(default=0.7, ge=0.0, le=1.0)


@router.post("/registry/match-test")
def match_test(body: MatchTest, session: Session = Depends(get_db)) -> dict:
    if body.anchor not in (None, "", "full", "prefix", "suffix", "floating"):
        raise HTTPException(422, "Invalid anchor")
    colours = []
    if body.colour:
        colours.append(LabelScore(label=body.colour, confidence=0.75 if body.secondary_colour else 1.0))
    if body.secondary_colour:
        colours.append(LabelScore(label=body.secondary_colour, confidence=0.25))
    make_models = [MakeModelScore(make=body.make, model=body.model or "", confidence=body.make_model_confidence)] \
        if body.make else []
    try:
        query = QueryEvidence(
            plate=PlateEvidence.from_text(body.plate, body.plate_confidence, body.anchor or None),
            colours=colours, body_type=body.body_type or None,
            body_confidence=body.body_confidence if body.body_type else 0.0, make_models=make_models,
            plate_format=_plate_format(body.plate_format),
        )
    except ValidationError as error:
        raise HTTPException(422, str(error)) from error
    return match(query, load_registry(session)).model_dump()

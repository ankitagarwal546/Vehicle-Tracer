"""Focused checks for registry coverage, evidence safety, report agreement and run recovery.

All plates here are fictional. Heavy models are replaced by small fakes.
"""
import csv
import html as html_text
import io
import json
import os
import re
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="vehicle-tracer-workflow-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_root / 'test.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_root / "uploads"))
os.environ.setdefault("ARTIFACT_DIR", str(_root / "artifacts"))
os.environ.setdefault("MODEL_DIR", str(_root / "models"))
os.environ.setdefault("REGISTRY_SIZE", "600")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.api import routes  # noqa: E402
from app.cv.detector_tracker import TrackObservation, VehicleTrack  # noqa: E402
from app.cv.frame_selection import reads_are_stable, select_plate_frames  # noqa: E402
from app.cv.plate_fusion import PlateRead, fuse_plate_reads  # noqa: E402
from app.cv.plate_ocr import OcrOutput, combine_variants, plate_image_warnings  # noqa: E402
from app.cv.plate_variants import build_variants  # noqa: E402
from app.cv.track_quality import assess_track  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import AuditEvent, Case, Clip, RegistryVehicle, TrackedVehicle  # noqa: E402
from app.engine.matcher import RegistryIndex, match  # noqa: E402
from app.engine.schemas import PlateEvidence, QueryEvidence, RegistryRecord  # noqa: E402
from app.main import app  # noqa: E402
from app.services import pipeline_orchestrator as orchestrator  # noqa: E402

UK_PLATE = "QA15ZZK"
ATTRIBUTES = {"colours": [], "body_type": {"label": "suv", "confidence": 0.7},
              "make_model": {"predictions": [{"make": "Unknown", "model": "Unknown", "confidence": 0}]}}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def uk_registry_cleanup():
    yield
    with SessionLocal() as session:
        session.execute(delete(RegistryVehicle).where(RegistryVehicle.source == "uploaded"))
        session.commit()
    orchestrator.invalidate_registry()


def _clip_file(name: str, frames: int = 10, seed: int = 0) -> Path:
    path = _root / name
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    generator = np.random.default_rng(seed)
    for _ in range(frames):
        writer.write(generator.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    writer.release()
    return path


def _new_case(client, title: str, plate_format: str = "uk", frames: int = 10) -> tuple[str, str]:
    case = client.post("/api/cases", json={"title": title}).json()
    path = _clip_file(f"{case['id']}.mp4", frames, seed=abs(hash(case["id"])) % 10_000)
    with path.open("rb") as handle:
        clip = client.post(f"/api/cases/{case['id']}/clips", files={"files": (path.name, handle, "video/mp4")},
                           data={"plate_format": plate_format}).json()["clips"][0]
    return case["id"], clip["id"]


def _add_track(case_id: str, clip_id: str, text: str, track_id: int, plate_format: str = "uk") -> str:
    with SessionLocal() as session:
        index = orchestrator.load_registry(session)
        evidence = QueryEvidence(plate=PlateEvidence.from_text(text), body_type="suv", body_confidence=0.7,
                                 plate_format=plate_format)
        vehicle = TrackedVehicle(
            case_id=case_id, clip_id=clip_id, track_id=track_id, first_seen_sec=0, last_seen_sec=1, frames_tracked=3,
            ai_evidence=evidence.model_dump(), active_evidence=evidence.model_dump(), attributes=ATTRIBUTES,
            fused_plate={"text": text, "slots": [], "matrix": [], "rejected_reads": [
                {"frame_idx": 7, "timestamp_sec": 0.7, "raw_text": "X", "reason": "too few characters"}]},
            match_result=match(evidence, index).model_dump(), keyframes=[], plate_reads=[],
        )
        session.add(vehicle)
        session.get(Case, case_id).status = "COMPLETED"
        session.commit()
        return vehicle.id


def _pdf_text(content: bytes) -> str:
    text = " ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    return re.sub(r"\s+", " ", text)


def _read(frame: int, text: str, conf: float = 0.9) -> PlateRead:
    return PlateRead(frame, frame / 5, text, [0.0 if c == "?" else conf for c in text], 100.0, 1000.0, conf)


# 1. Zero-coverage preflight and outcome
def test_uk_without_uk_records_warns_before_analysis_and_is_not_no_match(client, monkeypatch):
    case_id, clip_id = _new_case(client, "UK preflight")
    preflight = client.get(f"/api/cases/{case_id}/preflight").json()
    assert preflight["requires_acknowledgement"] is True
    row = preflight["coverage"][0]
    assert (row["plate_format"], row["format_label"], row["compatible_records"]) == ("uk", "UK", 0)
    warning = next(w for w in preflight["warnings"] if w["code"] == "NO_REGISTRY_COVERAGE")
    assert "UK" in warning["message"] and "0 compatible" in warning["message"]
    assert any("Upload a registry" in step for step in preflight["next_steps"])

    monkeypatch.setattr(routes, "asset_status", lambda: {"ready": True, "missing": [], "install_command": ""})
    submitted = []
    monkeypatch.setattr(routes, "submit_case", lambda value: submitted.append(value) or True)
    blocked = client.post(f"/api/cases/{case_id}/analyze")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "NO_REGISTRY_COVERAGE"
    assert submitted == []
    allowed = client.post(f"/api/cases/{case_id}/analyze", json={"acknowledge_no_coverage": True})
    assert allowed.status_code == 202 and submitted == [case_id]
    assert any(e["action"] == "NO_COVERAGE_ACKNOWLEDGED" for e in client.get(f"/api/cases/{case_id}").json()["audit"])

    _add_track(case_id, clip_id, UK_PLATE, 1)
    summary = client.get(f"/api/cases/{case_id}").json()["summary"]
    assert (summary["no_registry_coverage"], summary["no_registry_match"], summary["coverage_status"]) == (1, 0, "none")
    vehicle = client.get(f"/api/cases/{case_id}/vehicles").json()["vehicles"][0]
    assert vehicle["outcome"] == "NO_REGISTRY_COVERAGE" and vehicle["plate"] == UK_PLATE
    assert vehicle["registry_coverage"]["searched"] is False


# 2. Compatible registry changes matching only
def test_compatible_registry_enables_matching_without_changing_ocr_evidence(client, uk_registry_cleanup):
    case_id, clip_id = _new_case(client, "UK rematch")
    vehicle_id = _add_track(case_id, clip_id, UK_PLATE, 1)
    before = client.get(f"/api/cases/{case_id}/vehicles/{vehicle_id}").json()
    assert before["match_result"]["outcome"] == "NO_REGISTRY_COVERAGE"

    body = f"plate,make,model,body_type,colour\n{UK_PLATE},Fictional,Test,suv,white\n".encode()
    assert client.post("/api/registry/upload", files={"file": ("uk.csv", body, "text/csv")},
                       data={"mode": "merge"}).status_code == 200
    assert client.get(f"/api/cases/{case_id}/preflight").json()["requires_acknowledgement"] is False
    assert client.post(f"/api/cases/{case_id}/rescore").status_code == 200

    after = client.get(f"/api/cases/{case_id}/vehicles/{vehicle_id}").json()
    assert after["match_result"]["outcome"] == "PLATE_CANDIDATE"
    assert after["match_result"]["candidates"][0]["vehicle"]["plate"] == UK_PLATE
    assert after["match_result"]["registry_coverage"]["searched"] is True
    for field in ("fused_plate", "ai_evidence", "plate_reads", "keyframes"):
        assert after[field] == before[field]
    assert any(e["action"] == "REGISTRY_RESCORED" and "OCR evidence unchanged" in e["note"]
               for e in client.get(f"/api/cases/{case_id}").json()["audit"])


# 3. Weak characters are never filled
def test_weak_or_conflicting_characters_stay_unknown_despite_registry_and_format():
    conflict = fuse_plate_reads([_read(1, "QA15ZZK", 0.8), _read(2, "QA18ZZK", 0.8)])
    assert conflict.text == "QA1?ZZK"
    single = PlateRead(3, 0.6, "QA15ZZK", [0.92] * 6 + [0.5], 100, 1000, 0.8)
    assert fuse_plate_reads([single]).text == "QA15ZZ?"

    index = RegistryIndex([RegistryRecord(plate=UK_PLATE, body_type="suv", colour="white")])
    query = QueryEvidence(plate=PlateEvidence.from_text(conflict.text), plate_format="uk")
    result = match(query, index)
    assert result.query_plate == "QA1?ZZK" and query.plate.text == "QA1?ZZK"
    assert query.plate.slots[3].char == "?" and query.plate.slots[3].confidence == 0.0


def test_confident_minority_of_frames_cannot_set_a_character():
    reads = [_read(1, "OX71TRV", 0.99), _read(2, "OX71TRV", 0.99), _read(3, "OX71TRV", 0.7),
             _read(4, "CX71TRV", 0.45), _read(5, "DX71TRV", 0.45), _read(6, "QX71TRV", 0.4)]
    fused = fuse_plate_reads(reads)
    assert fused.text == "?X71TRV"
    assert fused.slots[0].unknown_reason == "only 3 of 6 frames agree on O"


# 4. Multi-frame fusion and rejected reads
def test_fusion_uses_several_frames_and_records_rejected_reads():
    fused = fuse_plate_reads([_read(10, "QA15??K"), _read(20, "QA??ZZK"), _read(30, "X")])
    assert fused.text == UK_PLATE
    assert fused.reads_used == 2 and fused.reads_rejected == 1
    payload = fused.to_dict()
    assert payload["rejected_reads"][0]["frame_idx"] == 30 and payload["rejected_reads"][0]["reason"]
    frames = {vote["frame_idx"] for slot in payload["slots"] for vote in slot["evidence"]}
    assert frames == {10, 20}


# 5. Enhancement cannot create confidence
def test_variants_preserve_source_and_interpolation_cannot_raise_confidence():
    raw = np.random.default_rng(3).integers(0, 255, (29, 67, 3), dtype=np.uint8)
    original = raw.copy()
    views, rectification = build_variants(raw)
    assert np.array_equal(raw, original) and np.array_equal(views["raw"], original)
    assert views["raw"] is not raw and views["upscale_2x"].shape[:2] == (58, 134)
    assert rectification.status in {"applied", "not_needed", "unavailable"} and rectification.reason

    combined = combine_variants({
        "raw": OcrOutput("QA15", [0.61, 0.62, 0.63, 0.64]),
        "upscale_2x": OcrOutput("QA15", [0.99] * 4),
        "upscale_4x": OcrOutput("QA15", [0.99] * 4),
        "unsharp": OcrOutput("QA15", [0.99] * 4),
    })
    assert all(value <= limit for value, limit in zip(combined.confidences, [0.61, 0.62, 0.63, 0.64]))

    derived_only = combine_variants({"raw": OcrOutput("QA1", [0.9, 0.9, 0.9]),
                                     "upscale_4x": OcrOutput("QA8", [0.99, 0.99, 0.99]),
                                     "unsharp": OcrOutput("QA8", [0.99, 0.99, 0.99]),
                                     "gamma": OcrOutput("QA8", [0.99, 0.99, 0.99])})
    assert derived_only.text[2] == "1" or derived_only.source_supported[2] is False


def test_small_crop_regression_keeps_unknowns_and_warns():
    warnings = plate_image_warnings(67, 29, 0.2)
    assert any("67×29" in item and "cannot restore" in item for item in warnings)
    weak = PlateRead(1, 0.2, "QA15ZZK", [0.92, 0.92, 0.92, 0.5, 0.92, 0.5, 0.92], 40, 1943, 0.7)
    assert fuse_plate_reads([weak]).text == "QA1?Z?K"


def test_frame_selection_skips_near_duplicates_and_stops_only_on_stable_reads():
    image = np.random.default_rng(5).integers(0, 255, (60, 90, 3), dtype=np.uint8)
    other = np.random.default_rng(6).integers(0, 255, (60, 90, 3), dtype=np.uint8)
    make = lambda frame, crop: TrackObservation(frame, frame / 10, (0, 0, 90, 60), 0.9, 100, crop, b"",
                                                target_in_crop=(0, 0, 90, 60))
    selection = select_plate_frames([make(1, image), make(2, image.copy()), make(3, other)])
    assert [item.frame_idx for item in selection.selected] == [1, 3] and selection.near_duplicates == 1
    stable = [_read(i, UK_PLATE, 0.95) for i in range(5)]
    assert reads_are_stable(stable)
    assert not reads_are_stable(stable[:4])
    assert not reads_are_stable([*stable[:4], _read(9, "QA15ZZX", 0.95)])


# 6. All outputs agree
def test_workspace_html_pdf_csv_json_agree_on_counts_and_coverage(client):
    case_id, clip_id = _new_case(client, "Agreement")
    for track_id, text in enumerate((UK_PLATE, "QB16YYL", "QA1", ""), start=1):
        _add_track(case_id, clip_id, text, track_id)
    summary = client.get(f"/api/cases/{case_id}").json()["summary"]
    assert (summary["tracks"], summary["no_registry_coverage"], summary["insufficient_plate"],
            summary["unreadable_plate"], summary["readable_plates"], summary["partial_plates"],
            summary["no_plate_chars"]) == (4, 2, 1, 1, 2, 1, 1)
    outcomes = Counter(v["outcome"] for v in client.get(f"/api/cases/{case_id}/vehicles").json()["vehicles"])
    assert outcomes["NO_REGISTRY_COVERAGE"] == summary["no_registry_coverage"]

    html = client.get(f"/api/cases/{case_id}/report/html").text
    for value, label in ((4, "Vehicle tracks"), (2, "No registry coverage"), (0, "No registry match"),
                         (1, "Partial plate only"), (1, "Plate unreadable"), (2, "Readable plates")):
        assert f"<b>{value}</b><span>{label}</span>" in html
    sentence = "2 readable plate(s) were not searched."
    assert sentence in re.sub(r"<[^>]+>", "", html)
    assert "synthetic" in html.lower() and "not probabilities" in html

    pdf = _pdf_text(client.get(f"/api/cases/{case_id}/report/pdf").content)
    assert sentence in pdf and "not no-match results" in pdf and "Registry Coverage" in pdf

    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/cases/{case_id}/export.csv").text)))
    assert Counter(row["outcome"] for row in rows) == outcomes
    assert sum(row["registry_searched"] == "True" for row in rows) == 0
    exported = json.loads(client.get(f"/api/cases/{case_id}/export.json").text)
    assert exported["summary"]["no_registry_coverage"] == 2 and len(exported["tracks"]) == 4
    assert exported["clips"][0]["sha256"] and exported["audit"]


def test_latin_camera_reading_uk_plates_is_flagged_without_changing_outcomes(client):
    case_id, clip_id = _new_case(client, "Default format", "latin_any")
    for track_id, text in enumerate(("QA15ZZK", "QB16YYL", "QC17XXM"), start=1):
        _add_track(case_id, clip_id, text, track_id, "latin_any")
    summary = client.get(f"/api/cases/{case_id}").json()["summary"]
    assert summary["no_registry_coverage"] == 0 and summary["no_registry_match"] == 3
    hint = summary["format_hints"][0]
    assert (hint["family"], hint["reads"], hint["complete_reads"]) == ("uk", 3, 3)
    assert "may reflect missing coverage" in hint["message"]
    assert hint["message"] in html_text.unescape(client.get(f"/api/cases/{case_id}/report/html").text)
    assert client.patch(f"/api/cases/{case_id}/clips/{clip_id}", json={"plate_format": "uk"}).status_code == 200
    assert client.get(f"/api/cases/{case_id}").json()["summary"]["format_changed"] is True
    assert client.post(f"/api/cases/{case_id}/rescore").status_code == 200
    updated = client.get(f"/api/cases/{case_id}").json()["summary"]
    assert (updated["no_registry_coverage"], updated["no_registry_match"], updated["format_hints"]) == (3, 0, [])


# 7. Missing capture time
def test_missing_time_disables_temporal_validation_in_ui_data_and_reports(client):
    case_id, clip_id = _new_case(client, "No time")
    _add_track(case_id, clip_id, UK_PLATE, 1)
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["summary"]["temporal_status"] == "unavailable"
    note = "Capture time is missing, so temporal validation is disabled."
    assert detail["summary"]["temporal_note"] == note
    assert any(w["code"] == "MISSING_CAPTURE_TIME" for w in detail["preflight"]["warnings"])
    assert note in client.get(f"/api/cases/{case_id}/report/html").text
    assert note in _pdf_text(client.get(f"/api/cases/{case_id}/report/pdf").content)


# 8. One clip
def test_single_clip_case_does_not_claim_cross_camera_validation(client):
    case_id, clip_id = _new_case(client, "One clip")
    _add_track(case_id, clip_id, UK_PLATE, 1)
    summary = client.get(f"/api/cases/{case_id}").json()["summary"]
    note = "This case has one clip, so cross-camera re-identification was not tested."
    assert summary["cross_camera_status"] == "not_tested_single_clip" and summary["cross_camera_note"] == note
    html = client.get(f"/api/cases/{case_id}/report/html").text
    assert note in html and "No pair of tracks" not in html
    pdf = _pdf_text(client.get(f"/api/cases/{case_id}/report/pdf").content)
    assert note in pdf and "No pair of tracks" not in pdf


# 9. Long-clip progress, failure and cancellation
class FakeDetector:
    weights_name = "fake"

    def __init__(self, tracks: int, frames: int):
        self.tracks, self.frames = tracks, frames

    def track_clip(self, _frames, on_frame=None):
        for count in range(1, self.frames + 1):
            if on_frame:
                on_frame(count)
        result = []
        for track_id in range(1, self.tracks + 1):
            # Tracks overlap in time and look different, so stitching correctly keeps them apart.
            crop = np.random.default_rng(track_id).integers(0, 255, (80, 120, 3), dtype=np.uint8)
            jpeg = cv2.imencode(".jpg", crop)[1].tobytes()
            track = VehicleTrack(track_id=track_id, first_seen_sec=0.0, last_seen_sec=2.0)
            for step in range(6):
                bbox = (track_id * 130, step * 2, track_id * 130 + 100, step * 2 + 70)
                track.add(TrackObservation(step * 3, step / 3, bbox, 0.8, 80.0 + step, crop.copy(), jpeg,
                                           target_in_crop=(5, 5, 110, 75)), "car", 0.8)
            result.append(track)
        return result


class FakeReader:
    workers = 2
    cache_hits = 0
    engine = "fake"
    name = "fake"
    errors: dict = {}

    def __init__(self, on_call=None):
        self.on_call = on_call
        self.calls = 0
        self.lock = threading.Lock()

    def inspect_vehicle(self, *_args):
        with self.lock:
            self.calls += 1
            call = self.calls
        if self.on_call:
            self.on_call(call)
        return None, "no plate detected"

    def read_stack(self, _observations):
        return None, None


class FakeClip:
    available = False
    error = None


def _wait(case_id: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while orchestrator.is_running(case_id):
        assert time.monotonic() < deadline, "analysis did not finish"
        time.sleep(0.02)


def _rows(case_id: str) -> tuple[set[str], str | None, str | None, str]:
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        ids = {vehicle.id for vehicle in session.query(TrackedVehicle).filter_by(case_id=case_id)}
        return ids, case.active_run_id, case.live_run_id, case.status


def test_long_clip_progress_failure_cancel_and_retry_stay_coherent(client, monkeypatch):
    case_id, clip_id = _new_case(client, "Long clip", "latin_any", frames=240)
    with SessionLocal() as session:
        digest = session.get(Clip, clip_id).sha256
    monkeypatch.setattr(orchestrator.models, "load", lambda: None)
    monkeypatch.setattr(orchestrator.models, "detector", FakeDetector(tracks=12, frames=200))
    monkeypatch.setattr(orchestrator.models, "clip", FakeClip())
    monkeypatch.setattr(orchestrator.models, "reader", FakeReader())

    assert orchestrator.submit_case(case_id)
    _wait(case_id)
    events = orchestrator.progress_bus.since(case_id, 0)
    percents = [event["percent"] for event in events]
    assert percents == sorted(percents) and percents[-1] == 100.0 and events[-1]["status"] == "COMPLETED"
    assert {"tracking", "recognition", "done"} <= {event["stage"] for event in events}
    assert all("elapsed_sec" in event and event["stage_label"] for event in events)
    assert max(event.get("tracks_done", 0) for event in events) == 12
    first_ids, first_run, live, status = _rows(case_id)
    assert (len(first_ids), live, status) == (12, None, "COMPLETED") and first_run
    vehicles = client.get(f"/api/cases/{case_id}/vehicles").json()["vehicles"]
    assert all(v["track_quality"]["plate_inspection"]["rejections"] for v in vehicles)

    def fail(call):
        if call == 8:
            raise RuntimeError("simulated OCR failure")

    monkeypatch.setattr(orchestrator.models, "reader", FakeReader(fail))
    assert orchestrator.submit_case(case_id)
    _wait(case_id)
    assert orchestrator.progress_bus.since(case_id, 0)[-1]["status"] == "FAILED"
    ids, run, live, status = _rows(case_id)
    assert (ids, run, live, status) == (first_ids, first_run, None, "FAILED")
    detail = client.get(f"/api/cases/{case_id}").json()
    assert "simulated OCR failure" in detail["error"] and detail["has_completed_run"] is True
    assert detail["summary"]["tracks"] == 12
    assert client.get(f"/api/cases/{case_id}/report/html").status_code == 200

    monkeypatch.setattr(orchestrator.models, "reader",
                        FakeReader(lambda call: orchestrator.request_cancel(case_id) if call == 5 else None))
    assert orchestrator.submit_case(case_id)
    _wait(case_id)
    assert orchestrator.progress_bus.since(case_id, 0)[-1]["status"] == "CANCELLED"
    ids, run, live, status = _rows(case_id)
    assert (ids, run, live, status) == (first_ids, first_run, None, "CANCELLED")
    assert client.post(f"/api/cases/{case_id}/cancel").status_code == 409

    monkeypatch.setattr(orchestrator.models, "reader", FakeReader())
    assert orchestrator.submit_case(case_id)
    _wait(case_id)
    retry_ids, retry_run, live, status = _rows(case_id)
    assert (len(retry_ids), live, status) == (12, None, "COMPLETED")
    assert retry_run != first_run and not retry_ids & first_ids
    with SessionLocal() as session:
        assert session.get(Clip, clip_id).sha256 == digest
        actions = [e.action for e in session.query(AuditEvent).filter_by(case_id=case_id)]
    assert {"ANALYSIS_FAILED", "ANALYSIS_CANCELLED", "ANALYSIS_COMPLETED"} <= set(actions)


def test_track_quality_grades_without_suppressing():
    crop = np.zeros((40, 60, 3), dtype=np.uint8)
    track = VehicleTrack(track_id=1, first_seen_sec=1.0, last_seen_sec=1.2)
    track.add(TrackObservation(1, 1.0, (0, 0, 20, 20), 0.3, 5.0, crop, b"", truncated=True, lower_occlusion=0.8),
              "car", 0.3)
    quality = assess_track(track)
    assert quality["tier"] == "review" and quality["reasons"] and quality["sampled_frames"] == 1

"""API contract tests against an isolated database. Heavy CV models are not loaded here."""
import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="vehicle-tracer-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_root / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_root / "uploads")
os.environ["ARTIFACT_DIR"] = str(_root / "artifacts")
os.environ["MODEL_DIR"] = str(_root / "models")
os.environ["REGISTRY_SIZE"] = "600"

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Case, Clip, CrossCameraEntity, TrackedVehicle  # noqa: E402
from app.engine.matcher import match  # noqa: E402
from app.engine.schemas import PlateEvidence, QueryEvidence, RegistryRecord  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def clip_path():
    path = _root / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    generator = np.random.default_rng(1)
    for _ in range(10):
        writer.write(generator.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    writer.release()
    return path


def test_health_reports_registry(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["registry_count"] == 600 and body["synthetic_count"] == 600


def test_case_and_clip_chain_of_custody(client, clip_path):
    case = client.post("/api/cases", json={"title": "Custody"}).json()
    with clip_path.open("rb") as handle:
        response = client.post(f"/api/cases/{case['id']}/clips", files={"files": ("a.mp4", handle, "video/mp4")},
                               data={"camera_label": "North", "recorded_at": "2026-01-01T10:00:00Z"})
    assert response.status_code == 201
    clip = response.json()["clips"][0]
    assert len(clip["sha256"]) == 64 and clip["camera_label"] == "North" and clip["width"] == 160
    with clip_path.open("rb") as handle:
        duplicate = client.post(f"/api/cases/{case['id']}/clips", files={"files": ("b.mp4", handle, "video/mp4")})
    assert duplicate.status_code == 409


def test_rejects_unsupported_upload(client):
    case = client.post("/api/cases", json={"title": "Bad"}).json()
    response = client.post(f"/api/cases/{case['id']}/clips", files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    assert response.status_code == 415


def test_analyze_requires_clip(client):
    case = client.post("/api/cases", json={"title": "Empty"}).json()
    assert client.post(f"/api/cases/{case['id']}/analyze").status_code == 422


def test_registry_search_and_upload(client):
    assert client.get("/api/registry", params={"q": "MH12DE1433"}).json()["total"] == 1
    csv_body = b"plate,make,model,body_type,colour,status\nGA01AB1234,Tata,Nexon,suv,red,ACTIVE\nbad!,a,b,suv,red,ACTIVE\n"
    result = client.post("/api/registry/upload", files={"file": ("r.csv", csv_body, "text/csv")}).json()
    assert result["inserted"] == 1 and result["rejected"] == 1


def test_match_sandbox(client):
    result = client.post("/api/registry/match-test", json={"plate": "MH12DE14?3", "colour": "white", "body_type": "suv"}).json()
    assert result["outcome"] == "AMBIGUOUS" and result["rejected_candidates"][0]["vehicle"]["plate"] == "MH12DE1433"
    exact = client.post("/api/registry/match-test", json={"plate": "MH12DE1433", "colour": "white", "body_type": "suv"}).json()
    assert exact["status"] == "CONFIDENT_SHORTLIST" and exact["candidates"][0]["vehicle"]["plate"] == "MH12DE1433"
    assert client.post("/api/registry/match-test", json={"plate": "ZZ99QQ0000"}).json()["status"] == "NO_CONFIDENT_MATCH"


def test_override_reranks_with_audit_and_report(client):
    with SessionLocal() as session:
        case = Case(title="Override")
        session.add(case)
        session.flush()
        clip = Clip(case_id=case.id, filename="c.mp4", stored_path="c.mp4", sha256="a" * 64, size_bytes=1, camera_label="Cam")
        session.add(clip)
        session.flush()
        evidence = QueryEvidence(plate=PlateEvidence.from_text("MH12DE14?3"), body_type="suv", body_confidence=0.7)
        vehicle = TrackedVehicle(
            case_id=case.id, clip_id=clip.id, track_id=1, first_seen_sec=0, last_seen_sec=1, frames_tracked=3,
            ai_evidence=evidence.model_dump(), active_evidence=evidence.model_dump(),
            attributes={"colours": [], "body_type": {"label": "suv", "confidence": 0.7},
                        "make_model": {"predictions": [{"make": "Unknown", "model": "Unknown", "confidence": 0}]}},
            fused_plate={"text": "MH12DE14?3", "slots": [], "matrix": []}, match_result={},
            keyframes=[], plate_reads=[],
        )
        session.add(vehicle)
        session.commit()
        case_id, vehicle_id = case.id, vehicle.id

    response = client.post(f"/api/cases/{case_id}/vehicles/{vehicle_id}/override",
                           json={"slots": [{"position": 8, "char": "8"}], "colour": "white", "body_type": "sedan"})
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle"]["top_plate"] == "MH12DE1483"
    assert body["rerank_ms"] < 50
    assert {"plate_slot_9", "colour", "body_type"} <= {e["field"] for e in body["audit"]}
    report = client.get(f"/api/cases/{case_id}/report/html").text
    assert "MH12DE1483" in report and "includes investigator-verified values" in report
    pdf = client.get(f"/api/cases/{case_id}/report/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"/api/cases/{case_id}/report/pdf", params={"appendix": True}).content.startswith(b"%PDF")
    reset = client.post(f"/api/cases/{case_id}/vehicles/{vehicle_id}/override", json={"reset": True}).json()
    assert reset["vehicle"]["overridden"] is False


def test_cross_camera_link_requires_review(client):
    with SessionLocal() as session:
        case = Case(title="Link review")
        session.add(case)
        session.flush()
        entity = CrossCameraEntity(case_id=case.id, fused_plate={"text": "MH12DE1433"}, timeline=[], links=[],
                                   match_result={}, evidence_tier="strong_plate")
        session.add(entity)
        session.commit()
        case_id, entity_id = case.id, entity.id
    assert client.get(f"/api/cases/{case_id}").json()["summary"]["possible_links"] == 1
    reviewed = client.post(f"/api/cases/{case_id}/entities/{entity_id}/review",
                           json={"decision": "confirmed", "note": "same vehicle"}).json()
    assert reviewed["review_status"] == "confirmed" and reviewed["reviewed_by"] == "Investigator"
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["summary"]["confirmed_links"] == 1
    assert any(event["action"] == "LINK_REVIEWED" for event in detail["audit"])
    assert client.post(f"/api/cases/{case_id}/entities/{entity_id}/review", json={"decision": "x"}).status_code == 422


def test_clip_script_can_be_updated(client, clip_path):
    case = client.post("/api/cases", json={"title": "Script"}).json()
    with clip_path.open("rb") as handle:
        clip = client.post(f"/api/cases/{case['id']}/clips", files={"files": ("s.mp4", handle, "video/mp4")},
                           data={"plate_script": "non_latin"}).json()["clips"][0]
    assert clip["plate_script"] == "non_latin"
    updated = client.patch(f"/api/cases/{case['id']}/clips/{clip['id']}", json={"plate_script": "latin"}).json()
    assert updated["plate_script"] == "latin"
    assert client.patch(f"/api/cases/{case['id']}/clips/{clip['id']}", json={"plate_script": "x"}).status_code == 422


def _case_with_outcomes():
    with SessionLocal() as session:
        case = Case(title="Report counts", status="COMPLETED")
        session.add(case)
        session.flush()
        clip_a = Clip(case_id=case.id, filename="synthetic_a.mp4", stored_path="a.mp4", sha256="a" * 64, size_bytes=1,
                      camera_label="A", plate_format="india_rto", timezone="Asia/Kolkata")
        clip_b = Clip(case_id=case.id, filename="b.mp4", stored_path="b.mp4", sha256="b" * 64, size_bytes=1,
                      camera_label="B", plate_format="uk")
        session.add_all([clip_a, clip_b])
        session.flush()
        attributes = {"colours": [], "body_type": {"label": "suv", "confidence": 0.7},
                      "make_model": {"predictions": [{"make": "Unknown", "model": "Unknown", "confidence": 0}]}}
        registry = [RegistryRecord(plate="MH12DE1433", body_type="suv", colour="white")]
        for clip, text, plate_format in ((clip_a, "MH12DE1433", "india_rto"), (clip_a, "", "india_rto"),
                                         (clip_b, "QA15ZZK", "uk")):
            evidence = QueryEvidence(plate=PlateEvidence.from_text(text), body_type="suv", body_confidence=0.7,
                                     plate_format=plate_format)
            session.add(TrackedVehicle(
                case_id=case.id, clip_id=clip.id, track_id=len(text) + 1, first_seen_sec=0, last_seen_sec=1,
                frames_tracked=3, ai_evidence=evidence.model_dump(), active_evidence=evidence.model_dump(),
                attributes=attributes, fused_plate={"text": text, "slots": [], "matrix": []},
                match_result=match(evidence, registry).model_dump(), keyframes=[], plate_reads=[],
            ))
        session.commit()
        return case.id, clip_a.id


def test_report_counts_match_case_summary_and_clip_scope(client):
    case_id, clip_id = _case_with_outcomes()
    summary = client.get(f"/api/cases/{case_id}").json()["summary"]
    assert (summary["tracks"], summary["plate_candidates"], summary["unreadable_plate"],
            summary["no_registry_match"]) == (3, 1, 1, 1)
    report = client.get(f"/api/cases/{case_id}/report/html").text
    for value, label in ((3, "Vehicle tracks"), (1, "Plate-supported"), (1, "No registry match"),
                         (1, "Plate unreadable")):
        assert f"<b>{value}</b><span>{label}</span>" in report
    assert "Synthetic test fixture" in report
    scoped = client.get(f"/api/cases/{case_id}/report/html", params={"clip_id": clip_id}).text
    assert "<b>2</b><span>Vehicle tracks</span>" in scoped and "QA15ZZK" not in scoped
    assert client.get(f"/api/cases/{case_id}/report/html", params={"clip_id": "missing"}).status_code == 404
    assert client.get(f"/api/cases/{case_id}/report/pdf", params={"clip_id": clip_id}).content.startswith(b"%PDF")


def test_analysis_reports_missing_models_without_downloading(client, clip_path):
    case = client.post("/api/cases", json={"title": "No models"}).json()
    with clip_path.open("rb") as handle:
        client.post(f"/api/cases/{case['id']}/clips", files={"files": ("m.mp4", handle, "video/mp4")})
    response = client.post(f"/api/cases/{case['id']}/analyze")
    assert response.status_code == 503 and "download_models.py" in response.json()["detail"]
    assets = client.get("/api/health").json()["models"]["assets"]
    assert assets["ready"] is False and assets["missing"]


def test_evidence_is_read_only_and_time_uses_camera_timezone(client, clip_path):
    case = client.post("/api/cases", json={"title": "Custody"}).json()
    with clip_path.open("rb") as handle:
        clip = client.post(f"/api/cases/{case['id']}/clips", files={"files": ("t.mp4", handle, "video/mp4")},
                           data={"recorded_at": "2026-01-01T10:00", "timezone": "Asia/Kolkata",
                                 "plate_format": "uk"}).json()["clips"][0]
    assert clip["recorded_at"].startswith("2026-01-01T04:30") and clip["plate_format"] == "uk"
    with SessionLocal() as session:
        stored = Path(session.get(Clip, clip["id"]).stored_path)
    assert stored.stat().st_mode & 0o222 == 0
    bad = client.patch(f"/api/cases/{case['id']}/clips/{clip['id']}", json={"timezone": "Mars/Base"})
    assert bad.status_code == 422

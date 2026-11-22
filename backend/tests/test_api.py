"""API contract tests against an isolated database. Heavy CV models are not loaded here."""
import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="vehicle-tracer-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_root / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_root / "uploads")
os.environ["ARTIFACT_DIR"] = str(_root / "artifacts")
os.environ["MODEL_DIR"] = str(_root / "models")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Case, TrackedVehicle  # noqa: E402
from app.engine.schemas import PlateEvidence, QueryEvidence  # noqa: E402
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
    assert body["status"] == "ok" and body["registry_count"] == 600


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
    assert result["status"] == "CONFIDENT_SHORTLIST" and result["candidates"][0]["vehicle"]["plate"] == "MH12DE1433"
    assert client.post("/api/registry/match-test", json={"plate": "ZZ99QQ0000"}).json()["status"] == "NO_CONFIDENT_MATCH"


def test_override_reranks_with_audit_and_report(client):
    with SessionLocal() as session:
        case = Case(title="Override")
        session.add(case)
        session.flush()
        from app.db.models import Clip

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
    reset = client.post(f"/api/cases/{case_id}/vehicles/{vehicle_id}/override", json={"reset": True}).json()
    assert reset["vehicle"]["overridden"] is False

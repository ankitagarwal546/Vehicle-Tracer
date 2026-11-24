"""Sign-in protects every case, evidence and registry route once AUTH_PASSWORD is set."""
import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="vitra-auth-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_root / 'test.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_root / "uploads"))
os.environ.setdefault("ARTIFACT_DIR", str(_root / "artifacts"))
os.environ.setdefault("MODEL_DIR", str(_root / "models"))
os.environ.setdefault("REGISTRY_SIZE", "600")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "test-only-passphrase"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_username", "investigator")
    monkeypatch.setattr(settings, "auth_password", PASSWORD)
    auth._failures.clear()
    with TestClient(app) as test_client:
        yield test_client
    auth._failures.clear()


def test_protected_routes_need_sign_in(client):
    assert client.get("/api/health").status_code == 200
    for path in ("/api/cases", "/api/registry", "/artifacts/anything.jpg"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/auth/session").json() == {"auth_enabled": True, "authenticated": False, "username": None}


def test_sign_in_and_sign_out(client):
    assert client.post("/api/auth/login", json={"username": "investigator", "password": "wrong"}).status_code == 401
    response = client.post("/api/auth/login", json={"username": "investigator", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/cases").status_code == 200
    assert client.get("/api/auth/session").json()["username"] == "investigator"
    client.post("/api/auth/logout")
    assert client.get("/api/cases").status_code == 401


def test_tampered_or_foreign_tokens_are_rejected(client):
    token = auth.issue_token("investigator")
    client.cookies.set(auth.COOKIE_NAME, token[:-4] + "AAAA")
    assert client.get("/api/cases").status_code == 401
    client.cookies.set(auth.COOKIE_NAME, auth.issue_token("someone-else"))
    assert client.get("/api/cases").status_code == 401


def test_repeated_failures_lock_the_client_out(client):
    for _ in range(auth.MAX_FAILURES):
        client.post("/api/auth/login", json={"username": "investigator", "password": "nope"})
    locked = client.post("/api/auth/login", json={"username": "investigator", "password": PASSWORD})
    assert locked.status_code == 429


def test_auth_is_off_without_a_password(monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "")
    with TestClient(app) as test_client:
        assert test_client.get("/api/cases").status_code == 200
        assert test_client.get("/api/auth/session").json()["authenticated"] is True


def test_require_auth_refuses_to_start_without_password(monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "")
    monkeypatch.setattr(settings, "require_auth", True)
    with pytest.raises(RuntimeError):
        auth.check_configuration()


def test_cross_site_writes_are_blocked(client):
    blocked = client.post("/api/auth/login", json={"username": "investigator", "password": PASSWORD},
                          headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403
    allowed = client.post("/api/auth/login", json={"username": "investigator", "password": PASSWORD},
                          headers={"Origin": "http://testserver"})
    assert allowed.status_code == 200

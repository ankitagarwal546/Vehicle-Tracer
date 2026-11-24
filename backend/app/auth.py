"""Sign-in for deployed instances.

Auth is on whenever AUTH_PASSWORD is set. Sessions are HMAC-signed, HTTP-only cookies, so the
browser sends them automatically with fetch, EventSource, report links and evidence images.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

log = logging.getLogger(__name__)

COOKIE_NAME = "vitra_session"
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/session"}
PROTECTED_PREFIXES = ("/api/", "/artifacts/")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300

_secret = (settings.session_secret or secrets.token_hex(32)).encode()
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def auth_enabled() -> bool:
    return bool(settings.auth_password)


def check_configuration() -> None:
    if settings.require_auth and not auth_enabled():
        raise RuntimeError("REQUIRE_AUTH is set but AUTH_PASSWORD is empty. Set AUTH_PASSWORD before starting VITRA.")
    if not auth_enabled():
        log.warning("AUTH_PASSWORD is not set, so sign-in is disabled. Only run like this on a private machine.")
    elif not settings.session_secret:
        log.warning("SESSION_SECRET is not set, so everyone is signed out whenever the server restarts.")


def _sign(payload: str) -> str:
    return hmac.new(_secret, payload.encode(), hashlib.sha256).hexdigest()


def issue_token(username: str) -> str:
    expires = int(time.time() + settings.session_hours * 3600)
    payload = f"{username}|{expires}|{secrets.token_hex(8)}"
    return base64.urlsafe_b64encode(f"{payload}|{_sign(payload)}".encode()).decode()


def read_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        username, expires, nonce, signature = base64.urlsafe_b64decode(token.encode()).decode().split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(signature, _sign(f"{username}|{expires}|{nonce}")):
        return None
    if not expires.isdigit() or int(expires) < time.time() or username != settings.auth_username:
        return None
    return username


def current_user(request: Request) -> str | None:
    return read_token(request.cookies.get(COOKIE_NAME))


def _cross_site(request: Request) -> bool:
    """A write whose Origin is another site. Guards against CSRF when the cookie is SameSite=None."""
    origin = request.headers.get("origin")
    if not origin:
        return False
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return urlsplit(origin).netloc.lower() != host.split(",")[0].strip().lower()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if auth_enabled() and request.method in UNSAFE_METHODS and path.startswith("/api/") and _cross_site(request):
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
        if auth_enabled() and request.method != "OPTIONS" and path.startswith(PROTECTED_PREFIXES) and path not in PUBLIC_PATHS:
            user = current_user(request)
            if user is None:
                return JSONResponse({"detail": "Sign in required"}, status_code=401)
            request.state.user = user
        return await call_next(request)


def _client_key(request: Request) -> str:
    # Cloudflare sets CF-Connecting-IP itself, so a client cannot spoof it the way it can prefix X-Forwarded-For.
    if request.headers.get("cf-connecting-ip"):
        return request.headers["cf-connecting-ip"].strip()
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _locked_for(key: str) -> int:
    now = time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(key, []) if now - t < LOCKOUT_SECONDS]
        _failures[key] = recent
        if len(recent) >= MAX_FAILURES:
            return int(LOCKOUT_SECONDS - (now - recent[0])) + 1
    return 0


def _record_failure(key: str) -> None:
    with _failures_lock:
        _failures.setdefault(key, []).append(time.time())


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


router = APIRouter(prefix="/api/auth")


def _set_cookie(response: Response, value: str, max_age: int) -> None:
    response.set_cookie(COOKIE_NAME, value, max_age=max_age, httponly=True, secure=settings.cookie_secure,
                        samesite=settings.cookie_samesite, path="/")


@router.get("/session")
def session(request: Request) -> dict:
    user = current_user(request) if auth_enabled() else None
    return {"auth_enabled": auth_enabled(), "authenticated": not auth_enabled() or user is not None, "username": user}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    if not auth_enabled():
        return {"auth_enabled": False, "authenticated": True, "username": None}
    key = _client_key(request)
    wait = _locked_for(key)
    if wait:
        raise HTTPException(429, f"Too many failed attempts. Try again in {wait} seconds.")
    user_ok = hmac.compare_digest(body.username.strip().encode(), settings.auth_username.encode())
    password_ok = hmac.compare_digest(body.password.encode(), settings.auth_password.encode())
    if not (user_ok and password_ok):
        _record_failure(key)
        raise HTTPException(401, "Incorrect username or password")
    with _failures_lock:
        _failures.pop(key, None)
    _set_cookie(response, issue_token(settings.auth_username), int(settings.session_hours * 3600))
    return {"auth_enabled": True, "authenticated": True, "username": settings.auth_username}


@router.post("/logout")
def logout(response: Response) -> dict:
    _set_cookie(response, "", 0)
    return {"auth_enabled": auth_enabled(), "authenticated": False, "username": None}

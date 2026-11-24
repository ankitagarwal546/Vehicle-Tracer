from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.auth import AuthMiddleware, check_configuration
from app.auth import router as auth_router
from app.config import PIPELINE_VERSION, settings
from app.db.database import SessionLocal, init_db
from app.db.seed_registry import seed_registry
from app.services.pipeline_orchestrator import recover_interrupted_runs, refresh_legacy_results


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    check_configuration()
    init_db()
    with SessionLocal() as session:
        seed_registry(session)
        # A job cannot survive a restart, so never leave a case stuck as running.
        recover_interrupted_runs(session)
        refresh_legacy_results(session)
    yield


app = FastAPI(title="VITRA", version=PIPELINE_VERSION, lifespan=lifespan)
# Added first so CORS stays the outermost layer and also covers 401 responses.
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
    expose_headers=["X-PDF-Engine"],
)
app.include_router(auth_router)
app.include_router(router)
app.mount("/artifacts", StaticFiles(directory=settings.artifact_dir), name="artifacts")
if settings.frontend_dist and settings.frontend_dist.is_dir():
    # Mounted last so every API and artifact route wins. The web app uses hash routing.
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="web")

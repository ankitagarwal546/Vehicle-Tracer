from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import PIPELINE_VERSION, settings
from app.db.database import SessionLocal, init_db
from app.db.seed_registry import seed_registry
from app.services.pipeline_orchestrator import recover_interrupted_runs, refresh_legacy_results


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    with SessionLocal() as session:
        seed_registry(session)
        # A job cannot survive a restart, so never leave a case stuck as running.
        recover_interrupted_runs(session)
        refresh_legacy_results(session)
    yield


app = FastAPI(title="VITRA", version=PIPELINE_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-PDF-Engine"],
)
app.include_router(router)
app.mount("/artifacts", StaticFiles(directory=settings.artifact_dir), name="artifacts")

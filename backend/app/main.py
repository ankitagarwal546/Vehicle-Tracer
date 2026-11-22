from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update

from app.api.routes import router
from app.config import PIPELINE_VERSION, settings
from app.db.database import SessionLocal, init_db
from app.db.models import Case
from app.db.seed_registry import seed_registry


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    with SessionLocal() as session:
        seed_registry(session)
        # A job cannot survive a restart, so never leave a case stuck as running.
        session.execute(
            update(Case).where(Case.status.in_(["QUEUED", "RUNNING"]))
            .values(status="FAILED", error="Interrupted by a server restart. Run the analysis again.")
        )
        session.commit()
    yield


app = FastAPI(title="Vehicle-Tracer", version=PIPELINE_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-PDF-Engine"],
)
app.include_router(router)
app.mount("/artifacts", StaticFiles(directory=settings.artifact_dir), name="artifacts")

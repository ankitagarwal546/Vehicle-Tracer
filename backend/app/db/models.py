from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class RegistryVehicle(Base):
    __tablename__ = "registry_vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    make: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64))
    body_type: Mapped[str] = mapped_column(String(32), index=True)
    colour: Mapped[str] = mapped_column(String(24), index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner_city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    source: Mapped[str] = mapped_column(String(16), default="synthetic", index=True)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="CREATED")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(24), nullable=True)
    runtime: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    clips: Mapped[list["Clip"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    vehicles: Mapped[list["TrackedVehicle"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    entities: Mapped[list["CrossCameraEntity"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="AuditEvent.created_at"
    )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    camera_label: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    codec: Mapped[str] = mapped_column(String(32), default="")
    plate_script: Mapped[str] = mapped_column(String(16), default="latin")
    processing: Mapped[dict] = mapped_column(JSON, default=dict)

    case: Mapped[Case] = relationship(back_populates="clips")
    vehicles: Mapped[list["TrackedVehicle"]] = relationship(back_populates="clip", cascade="all, delete-orphan")


class CrossCameraEntity(Base):
    __tablename__ = "cross_camera_entities"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    fused_plate: Mapped[dict] = mapped_column(JSON, default=dict)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    links: Mapped[list] = mapped_column(JSON, default=list)
    match_result: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    evidence_tier: Mapped[str] = mapped_column(String(32), default="unverified")
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped[Case] = relationship(back_populates="entities")
    vehicles: Mapped[list["TrackedVehicle"]] = relationship(back_populates="entity")


class TrackedVehicle(Base):
    __tablename__ = "tracked_vehicles"
    __table_args__ = (Index("ix_tracked_case_clip", "case_id", "clip_id"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("cross_camera_entities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    track_id: Mapped[int] = mapped_column(Integer)
    first_seen_sec: Mapped[float] = mapped_column(Float)
    last_seen_sec: Mapped[float] = mapped_column(Float)
    frames_tracked: Mapped[int] = mapped_column(Integer)
    best_crop: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyframes: Mapped[list] = mapped_column(JSON, default=list)
    plate_reads: Mapped[list] = mapped_column(JSON, default=list)
    fused_plate: Mapped[dict] = mapped_column(JSON, default=dict)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    active_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    match_result: Mapped[dict] = mapped_column(JSON, default=dict)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)

    case: Mapped[Case] = relationship(back_populates="vehicles")
    clip: Mapped[Clip] = relationship(back_populates="vehicles")
    entity: Mapped[CrossCameraEntity | None] = relationship(back_populates="vehicles")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[str | None] = mapped_column(String(12), nullable=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64))
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_extracted: Mapped[str | None] = mapped_column(Text, nullable=True)
    investigator_verified: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="audit_events")

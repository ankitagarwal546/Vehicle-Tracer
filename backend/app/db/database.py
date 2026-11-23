from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def build_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    built = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite else {})
    if is_sqlite:
        @event.listens_for(built, "connect")
        def _configure(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return built


engine = build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Upgrade databases created by an earlier release without losing cases."""
    additions = {
        "registry_vehicles": {"source": "VARCHAR(16) NOT NULL DEFAULT 'synthetic'"},
        "clips": {
            "plate_script": "VARCHAR(16) NOT NULL DEFAULT 'latin'",
            "plate_format": "VARCHAR(24) NOT NULL DEFAULT 'latin_any'",
            "timezone": "VARCHAR(64)",
            "latitude": "FLOAT",
            "longitude": "FLOAT",
        },
        "cases": {"active_run_id": "VARCHAR(16)", "live_run_id": "VARCHAR(16)"},
        "tracked_vehicles": {"run_id": "VARCHAR(16)"},
        "cross_camera_entities": {
            "run_id": "VARCHAR(16)",
            "review_status": "VARCHAR(16) NOT NULL DEFAULT 'proposed'",
            "evidence_tier": "VARCHAR(32) NOT NULL DEFAULT 'legacy_unverified'",
            "reviewed_by": "VARCHAR(120)",
            "reviewed_at": "TIMESTAMP",
            "review_note": "TEXT",
        },
    }
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
                    if (table, name) == ("clips", "plate_format"):
                        connection.execute(text("UPDATE clips SET plate_format = 'non_latin_digits' "
                                                "WHERE plate_script = 'non_latin'"))

"""
Backlog 2.1/2.2/2.3: Project + shot-list state.

Per README.md "Data" decision (backlog 0.4): B2 is the source of truth for
durable artifacts (scene.json, frames, manifests, clips), but project/shot
*state* needs a row store with transactional updates, since concurrent
writes (e.g. a B2 webhook later on) must not race. SQLite locally, Postgres
in production — same models, different ``DATABASE_URL``.

Backlog 2.4 adds ``ShotRecord``/``ShotVersionRecord``: the first two states
of the CLAUDE.md shot state machine (``DRAFT``, and ``REFINING`` once
backlog 3.6 lands) plus per-version Shot Spec storage. ``status`` is a
plain string column, not inferred from B2 object existence, per CLAUDE.md
("don't let state leak implicitly through file existence checks").
``ShotVersionRecord`` exists as its own table (not inlined on
``ShotRecord``) because the frontend's already-committed ``Shot.versions``
contract (``frontend/src/lib/api.ts``) and the version-scrub feature
(backlog 3.7) both need the full v1..vN history, not just the current one.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_project_id() -> str:
    return uuid.uuid4().hex[:12]


class ProjectRecord(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_project_id)
    scene_text: Mapped[str] = mapped_column(Text)
    # Set once backlog 7.3 writes previs/sequence.mp4 + manifest.json; the
    # paths are deterministic (storage/keys.py) but existence is state, and
    # state lives here, never inferred from B2 object existence (CLAUDE.md).
    sequence_key: Mapped[str | None] = mapped_column(String(512), default=None, nullable=True)
    sequence_manifest_key: Mapped[str | None] = mapped_column(
        String(512), default=None, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    shot_list_items: Mapped[list["ShotListItemRecord"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ShotListItemRecord.order",
    )
    shots: Mapped[list["ShotRecord"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ShotRecord.order",
    )


class ShotListItemRecord(Base):
    __tablename__ = "shot_list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    shot_id: Mapped[str] = mapped_column(String(64))
    order: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(Text, default="")
    shot_size: Mapped[str] = mapped_column(String(32), default="medium")

    project: Mapped[ProjectRecord] = relationship(back_populates="shot_list_items")


class ShotRecord(Base):
    __tablename__ = "shots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    shot_id: Mapped[str] = mapped_column(String(64))
    order: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    # Which version got locked (backlog 4.1). The locked frame/manifest B2
    # keys are deterministic from ids (storage/keys.py) so aren't stored;
    # this + status are the state.
    locked_version: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)
    # When the lock happened — the polling fallback (backlog 5.3) uses this
    # to give the webhook first claim on fresh locks.
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)

    project: Mapped[ProjectRecord] = relationship(back_populates="shots")
    versions: Mapped[list["ShotVersionRecord"]] = relationship(
        back_populates="shot",
        cascade="all, delete-orphan",
        order_by="ShotVersionRecord.version",
    )


class ShotVersionRecord(Base):
    __tablename__ = "shot_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shot_pk: Mapped[int] = mapped_column(ForeignKey("shots.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    # Full ShotSpec.model_dump_json() — kept as opaque text here so the
    # schema (models/shot_spec.py) stays the single source of truth for
    # the shape; the API layer re-validates it back into a ShotSpec.
    spec_json: Mapped[str] = mapped_column(Text)
    # B2 key of this version's generated frame (backlog 3.5); None until the
    # image stage has produced one for this version.
    frame_key: Mapped[str | None] = mapped_column(String(512), default=None, nullable=True)
    # Provider/model/prompt that actually served the generation — recorded
    # per version because the fallback chain (3.3) means it varies, and the
    # lock manifest (4.2) needs the truth for the locked version.
    provider: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    shot: Mapped[ShotRecord] = relationship(back_populates="versions")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./nova.db")


def _make_engine():
    url = _database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = _make_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

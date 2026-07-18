"""
FastAPI entrypoint. Serves the JSON API under /api and the built frontend
(frontend/dist/, a plain Vite SPA build) as static files from the same
process — one deployable, one uptime surface (README.md "Tech stack",
Nova_File_Structure.md "Architecture recap").

Run locally with: uvicorn nova.api.app:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from nova.api.routes import router
from nova.models.project import init_db
from nova.webhooks.lock_handler import router as webhook_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Nova", lifespan=_lifespan)
app.include_router(router)
# B2 Event Notifications POST here (backlog 5.2) — outside /api because it's
# a machine-to-machine surface, not part of the frontend contract.
app.include_router(webhook_router)

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    # html=True serves index.html for unmatched paths, so client-side
    # routes (e.g. /p/:projectId) resolve correctly on a hard refresh.
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")

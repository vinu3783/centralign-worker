"""FastAPI entrypoint."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import ROUTERS
from app.config import get_settings
from app.database.seed import seed_if_empty
from app.database.session import init_db, session_scope
from app.services.task_service import get_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db()
    if settings.seed_on_start:
        with session_scope() as db:
            seed_if_empty(db)
    manager = get_manager()
    manager.recover_orphans()
    logging.getLogger("centralign").info("CentrAlign Worker ready — mode=%s model=%s", manager.mode, manager.model_label)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CentrAlign Worker", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                       allow_methods=["*"], allow_headers=["*"])
    for router in ROUTERS:
        app.include_router(router)

    # Optional: serve the built frontend from the same origin (single-container deployment).
    static_dir = os.environ.get("STATIC_DIR")
    if static_dir and Path(static_dir, "index.html").exists():
        app.mount("/assets", StaticFiles(directory=Path(static_dir) / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = Path(static_dir) / path
            return FileResponse(candidate if path and candidate.is_file() else Path(static_dir) / "index.html")

    return app


app = create_app()

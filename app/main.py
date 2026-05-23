"""Entry point. `python -m app.main` (also what the systemd unit runs)."""

from __future__ import annotations

import time
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.routes import register_routes
from .config import load_config
from .logging_setup import setup_logging
from .pipeline import PipelineManager
from .storage import Database

log = structlog.get_logger(__name__)


def build_app() -> FastAPI:
    cfg = load_config()
    setup_logging(cfg.paths.log_dir)
    log.info("startup", version=__version__, cameras=len(cfg.cameras))

    app = FastAPI(title="pi5-hailo-vision", version=__version__)
    app.state.config = cfg
    app.state.version = __version__
    app.state.started_at = time.time()

    db = Database(cfg.paths.db_path, cfg.models.clip.embedding_dim)
    app.state.db = db

    mgr = PipelineManager(cfg=cfg, db=db)
    app.state.pipeline_manager = mgr

    @app.on_event("startup")
    async def _startup() -> None:
        await db.open()
        if cfg.cameras:
            await mgr.start()
        else:
            log.warning("no_cameras_configured", hint="edit ~/.config/pi5-hailo-vision/cameras.yaml")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await mgr.stop()
        await db.close()

    register_routes(app)

    # Serve the UI at the root.
    ui_dir = Path(__file__).parent / "ui"
    app.mount("/static", StaticFiles(directory=ui_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        return FileResponse(ui_dir / "index.html")

    return app


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.paths.log_dir)
    uvicorn.run(
        "app.main:build_app",
        factory=True,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
        access_log=False,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()

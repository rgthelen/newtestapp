"""HTTP + WebSocket routes."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse

log = structlog.get_logger(__name__)


def register_routes(app: FastAPI) -> None:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    async def health(request: Request) -> dict:
        return {"ok": True, "version": request.app.state.version}

    @router.get("/cameras")
    async def list_cameras(request: Request) -> dict:
        mgr = request.app.state.pipeline_manager
        items = []
        for cam_id, p in mgr.pipelines.items():
            snap = p.latest
            items.append(
                {
                    "id": cam_id,
                    "name": p.cfg.name,
                    "connected": p.source.connected,
                    "fps_in": round(p.source.fps_in, 1),
                    "fps_out": round(snap.fps_out, 1) if snap else 0.0,
                    "inference_ms": round(snap.inference_ms, 1) if snap else None,
                    "last_error": p.source.last_error,
                    "resolution": [snap.width, snap.height] if snap else None,
                }
            )
        return {"cameras": items}

    @router.get("/cameras/{camera_id}/state")
    async def camera_state(camera_id: str, request: Request) -> dict:
        p = request.app.state.pipeline_manager.get(camera_id)
        if p is None:
            raise HTTPException(404, "unknown camera")
        snap = p.latest
        if snap is None:
            return {"camera_id": camera_id, "ready": False}
        return {
            "camera_id": camera_id,
            "ready": True,
            "ts": snap.ts,
            "fps_in": snap.fps_in,
            "fps_out": snap.fps_out,
            "inference_ms": snap.inference_ms,
            "detections": snap.detections,
            "tracks": snap.tracks,
            "resolution": [snap.width, snap.height],
        }

    @router.get("/cameras/{camera_id}/snapshot.jpg")
    async def snapshot(camera_id: str, request: Request) -> Response:
        p = request.app.state.pipeline_manager.get(camera_id)
        if p is None:
            raise HTTPException(404, "unknown camera")
        jpeg = p.latest_jpeg
        if not jpeg:
            raise HTTPException(503, "no frame yet")
        return Response(content=jpeg, media_type="image/jpeg")

    @router.get("/cameras/{camera_id}/stream.mjpeg")
    async def mjpeg_stream(camera_id: str, request: Request) -> StreamingResponse:
        p = request.app.state.pipeline_manager.get(camera_id)
        if p is None:
            raise HTTPException(404, "unknown camera")

        async def gen():
            last_idx = -1
            while not await request.is_disconnected():
                jpeg = p.latest_jpeg
                snap = p.latest
                idx = snap.frame_idx if snap else -1
                if jpeg and idx != last_idx:
                    last_idx = idx
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                        + jpeg + b"\r\n"
                    )
                await asyncio.sleep(1 / max(5, p.cfg.fps))

        return StreamingResponse(
            gen(), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    @router.get("/events")
    async def events(
        request: Request,
        limit: int = Query(100, ge=1, le=500),
        camera_id: str | None = None,
        cls: str | None = None,
    ) -> dict:
        snap_base: Path = request.app.state.config.paths.snapshots_dir.resolve()
        rows = await request.app.state.db.recent_events(
            limit=limit, camera_id=camera_id, cls_name=cls,
        )
        return {"events": [_event_to_dict(r, snap_base) for r in rows]}

    @router.get("/search")
    async def search(
        request: Request,
        q: str = Query(..., min_length=1),
        top_k: int = Query(24, ge=1, le=100),
    ) -> dict:
        text_enc = request.app.state.pipeline_manager.clip_text
        if text_enc is None:
            raise HTTPException(503, "text encoder not initialized")
        loop = asyncio.get_running_loop()
        vec = await loop.run_in_executor(None, text_enc.encode, q)
        snap_base: Path = request.app.state.config.paths.snapshots_dir.resolve()
        rows = await request.app.state.db.search_by_embedding(vec, top_k=top_k)
        return {"query": q, "results": [_event_to_dict(r, snap_base) for r in rows]}

    @router.get("/snapshots/{path:path}")
    async def get_snapshot_file(path: str, request: Request) -> FileResponse:
        # Snapshots are stored under config.paths.snapshots_dir; only serve
        # files inside that dir.
        base: Path = request.app.state.config.paths.snapshots_dir
        full = (base / path).resolve()
        try:
            full.relative_to(base.resolve())
        except ValueError:
            raise HTTPException(403, "forbidden")
        if not full.exists():
            raise HTTPException(404, "not found")
        return FileResponse(full, media_type="image/jpeg")

    @router.get("/stats")
    async def stats(request: Request) -> dict:
        mgr = request.app.state.pipeline_manager
        db = request.app.state.db
        return {
            "uptime_s": time.time() - request.app.state.started_at,
            "cameras": len(mgr.pipelines),
            "embeddings_indexed": len(db._emb_ids),
        }

    @app.websocket("/ws/cameras/{camera_id}")
    async def ws_camera(websocket: WebSocket, camera_id: str) -> None:
        mgr = websocket.app.state.pipeline_manager
        p = mgr.get(camera_id)
        if p is None:
            await websocket.close(code=4404, reason="unknown camera")
            return
        await websocket.accept()
        last_idx = -1
        try:
            while True:
                snap = p.latest
                if snap is not None and snap.frame_idx != last_idx:
                    last_idx = snap.frame_idx
                    payload = {
                        "type": "state",
                        "camera_id": camera_id,
                        "ts": snap.ts,
                        "frame_idx": snap.frame_idx,
                        "width": snap.width,
                        "height": snap.height,
                        "fps_in": round(snap.fps_in, 1),
                        "fps_out": round(snap.fps_out, 1),
                        "inference_ms": round(snap.inference_ms, 1),
                        "detections": snap.detections,
                        "tracks": snap.tracks,
                    }
                    await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(1 / max(5, p.cfg.fps))
        except WebSocketDisconnect:
            return

    app.include_router(router)


def _event_to_dict(row, snap_base: Path) -> dict:
    snap_path = Path(row.snapshot_path)
    rel: str | None
    try:
        rel = str(snap_path.resolve().relative_to(snap_base))
    except (ValueError, OSError):
        rel = None
    return {
        "id": row.id,
        "camera_id": row.camera_id,
        "ts": row.ts,
        "track_id": row.track_id,
        "cls_name": row.cls_name,
        "confidence": round(row.confidence, 4),
        "bbox": row.bbox,
        "snapshot_url": f"/api/snapshots/{rel}" if rel else None,
        "score": round(row.score, 4) if row.score is not None else None,
    }

"""SQLite event store. Embeddings stored inline as BLOBs (float32 little-endian).

At <100k events brute-force cosine search in numpy is ~5ms — we don't need
FAISS yet. The embedding cache below keeps the matrix resident in RAM.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import aiosqlite
import numpy as np
import structlog

log = structlog.get_logger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id     TEXT NOT NULL,
    ts            REAL NOT NULL,
    track_id      INTEGER,
    cls_name      TEXT NOT NULL,
    confidence    REAL NOT NULL,
    bbox          TEXT NOT NULL,        -- JSON [x1,y1,x2,y2]
    snapshot_path TEXT NOT NULL,
    embedding     BLOB                  -- float32 vector
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_camera_ts ON events(camera_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_track ON events(camera_id, track_id);
"""


@dataclass
class EventRow:
    id: int
    camera_id: str
    ts: float
    track_id: int | None
    cls_name: str
    confidence: float
    bbox: list[float]
    snapshot_path: str
    score: float | None = None       # populated by similarity search


class Database:
    def __init__(self, path: Path, embedding_dim: int) -> None:
        self.path = path
        self.embedding_dim = embedding_dim
        self._conn: aiosqlite.Connection | None = None

        # In-memory matrix of embeddings (for fast search).
        self._emb_lock = asyncio.Lock()
        self._emb_ids: list[int] = []
        self._emb_matrix: np.ndarray | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        await self._load_embeddings()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _load_embeddings(self) -> None:
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT id, embedding FROM events WHERE embedding IS NOT NULL"
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return
        ids, vecs = [], []
        for row in rows:
            ids.append(row[0])
            v = np.frombuffer(row[1], dtype=np.float32)
            if v.shape[0] != self.embedding_dim:
                continue
            vecs.append(v)
        if vecs:
            self._emb_ids = ids
            self._emb_matrix = np.stack(vecs).astype(np.float32)
            log.info("db.embeddings.loaded", count=len(ids), dim=self.embedding_dim)

    async def insert_event(
        self,
        camera_id: str,
        ts: float,
        track_id: int | None,
        cls_name: str,
        confidence: float,
        bbox: list[float],
        snapshot_path: str,
        embedding: np.ndarray | None,
    ) -> int:
        import json

        assert self._conn is not None
        emb_blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
        cur = await self._conn.execute(
            """INSERT INTO events (camera_id, ts, track_id, cls_name, confidence, bbox, snapshot_path, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (camera_id, ts, track_id, cls_name, confidence, json.dumps(bbox), snapshot_path, emb_blob),
        )
        await self._conn.commit()
        event_id = cur.lastrowid or 0

        if embedding is not None:
            async with self._emb_lock:
                v = embedding.astype(np.float32).reshape(1, -1)
                if self._emb_matrix is None:
                    self._emb_matrix = v
                else:
                    self._emb_matrix = np.concatenate([self._emb_matrix, v], axis=0)
                self._emb_ids.append(event_id)

        return event_id

    async def recent_events(
        self,
        limit: int = 100,
        camera_id: str | None = None,
        cls_name: str | None = None,
    ) -> list[EventRow]:
        import json
        assert self._conn is not None
        q = "SELECT id, camera_id, ts, track_id, cls_name, confidence, bbox, snapshot_path FROM events"
        clauses, args = [], []
        if camera_id:
            clauses.append("camera_id = ?")
            args.append(camera_id)
        if cls_name:
            clauses.append("cls_name = ?")
            args.append(cls_name)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)

        async with self._conn.execute(q, args) as cur:
            rows = await cur.fetchall()
        return [
            EventRow(
                id=r[0], camera_id=r[1], ts=r[2], track_id=r[3],
                cls_name=r[4], confidence=r[5], bbox=json.loads(r[6]),
                snapshot_path=r[7],
            )
            for r in rows
        ]

    async def search_by_embedding(
        self, query_vec: np.ndarray, top_k: int = 24,
    ) -> list[EventRow]:
        import json
        assert self._conn is not None
        async with self._emb_lock:
            if self._emb_matrix is None or len(self._emb_ids) == 0:
                return []
            q = query_vec.astype(np.float32).reshape(-1)
            # Both sides are L2-normalized → dot product = cosine similarity.
            scores = self._emb_matrix @ q
            k = min(top_k, scores.shape[0])
            # argpartition for O(N), then sort the top-K.
            idx = np.argpartition(-scores, kth=k - 1)[:k]
            idx = idx[np.argsort(-scores[idx])]
            top_ids = [self._emb_ids[i] for i in idx]
            top_scores = [float(scores[i]) for i in idx]

        placeholders = ",".join("?" * len(top_ids))
        async with self._conn.execute(
            f"""SELECT id, camera_id, ts, track_id, cls_name, confidence, bbox, snapshot_path
                FROM events WHERE id IN ({placeholders})""",
            top_ids,
        ) as cur:
            rows = await cur.fetchall()

        by_id = {
            r[0]: EventRow(
                id=r[0], camera_id=r[1], ts=r[2], track_id=r[3],
                cls_name=r[4], confidence=r[5], bbox=json.loads(r[6]),
                snapshot_path=r[7],
            )
            for r in rows
        }
        results = []
        for eid, score in zip(top_ids, top_scores):
            row = by_id.get(eid)
            if row is None:
                continue
            row.score = score
            results.append(row)
        return results

    async def prune_older_than(self, days: int) -> int:
        assert self._conn is not None
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        cur = await self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        await self._conn.commit()
        return cur.rowcount or 0

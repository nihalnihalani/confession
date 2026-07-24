"""Durable runtime state for claims, results, events, jobs, and request controls.

SQLite is intentionally used through the standard library: the engine gets transactional
restart recovery without introducing a second service for the hackathon deployment. WAL
mode and short transactions keep the single-process API responsive. Production runs must
use one engine worker; horizontal scaling requires moving this interface to a shared
database and broker.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .models import AuditResult, Claim, Event, utcnow


class StateStore:
    """Thread-safe SQLite repository used as the engine's source of runtime truth."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _migrate(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                claim_json TEXT NOT NULL,
                result_json TEXT,
                reaudit_attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS idempotency (
                scope TEXT NOT NULL,
                request_key TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (scope, request_key)
            );
            CREATE TABLE IF NOT EXISTS rate_events (
                bucket TEXT NOT NULL,
                occurred_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rate_events
                ON rate_events(bucket, occurred_at);
            """
        )

    # -- claims/results -----------------------------------------------------

    def save_claim(self, claim: Claim, result: Optional[AuditResult] = None) -> None:
        now = utcnow().isoformat()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._connection.execute(
                    "SELECT result_json, created_at FROM claims WHERE id = ?",
                    (claim.id,),
                ).fetchone()
                result_json = (
                    result.model_dump_json()
                    if result is not None
                    else (current["result_json"] if current is not None else None)
                )
                created_at = current["created_at"] if current is not None else now
                self._connection.execute(
                    """
                    INSERT INTO claims (
                        id, claim_json, result_json, reaudit_attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, 0, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        claim_json = excluded.claim_json,
                        result_json = excluded.result_json,
                        updated_at = excluded.updated_at
                    """,
                    (claim.id, claim.model_dump_json(), result_json, created_at, now),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def load_claims(self) -> tuple[dict[str, Claim], dict[str, AuditResult]]:
        claims: dict[str, Claim] = {}
        results: dict[str, AuditResult] = {}
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, claim_json, result_json FROM claims ORDER BY created_at"
            ).fetchall()
        for row in rows:
            claim = Claim.model_validate_json(row["claim_json"])
            claims[claim.id] = claim
            if row["result_json"]:
                results[claim.id] = AuditResult.model_validate_json(row["result_json"])
        return claims, results

    def increment_reaudit_attempt(self, claim_id: str, max_attempts: int) -> Optional[int]:
        """Atomically spend one retry attempt, returning the new count or None at the cap."""
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT reaudit_attempts FROM claims WHERE id = ?",
                    (claim_id,),
                ).fetchone()
                if row is None or int(row["reaudit_attempts"]) >= max_attempts:
                    self._connection.execute("ROLLBACK")
                    return None
                count = int(row["reaudit_attempts"]) + 1
                self._connection.execute(
                    "UPDATE claims SET reaudit_attempts = ?, updated_at = ? WHERE id = ?",
                    (count, utcnow().isoformat(), claim_id),
                )
                self._connection.execute("COMMIT")
                return count
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def reaudit_attempts(self, claim_id: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT reaudit_attempts FROM claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
        return int(row["reaudit_attempts"]) if row is not None else 0

    # -- event history ------------------------------------------------------

    def append_event(self, event: Event, keep: int = 500) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "INSERT INTO events(event_json, created_at) VALUES (?, ?)",
                    (event.model_dump_json(), event.timestamp.isoformat()),
                )
                self._connection.execute(
                    """
                    DELETE FROM events
                    WHERE sequence NOT IN (
                        SELECT sequence FROM events ORDER BY sequence DESC LIMIT ?
                    )
                    """,
                    (keep,),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def load_events(self, limit: int = 500) -> list[Event]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_json FROM (
                    SELECT sequence, event_json FROM events
                    ORDER BY sequence DESC LIMIT ?
                ) ORDER BY sequence
                """,
                (limit,),
            ).fetchall()
        return [Event.model_validate_json(row["event_json"]) for row in rows]

    # -- background jobs ----------------------------------------------------

    def create_job(
        self,
        job_id: str,
        kind: str,
        payload: dict[str, Any],
        status: str = "queued",
    ) -> dict[str, Any]:
        now = utcnow().isoformat()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO jobs(
                    id, kind, status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (job_id, kind, status, json.dumps(payload), now, now),
            )
        return self.get_job(job_id) or {}

    def update_job(
        self,
        job_id: str,
        status: str,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE jobs SET
                    status = ?,
                    result_json = ?,
                    error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(result) if result is not None else None,
                    error,
                    utcnow().isoformat(),
                    job_id,
                ),
            )

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id, kind, status, payload_json, result_json, error,
                       created_at, updated_at
                FROM jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        return _job_row(row) if row is not None else None

    def recoverable_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, kind, status, payload_json, result_json, error,
                       created_at, updated_at
                FROM jobs WHERE status IN ('queued', 'running')
                ORDER BY created_at
                """
            ).fetchall()
        return [_job_row(row) for row in rows]

    # -- request idempotency ------------------------------------------------

    def get_idempotent(self, scope: str, request_key: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT response_json FROM idempotency WHERE scope = ? AND request_key = ?",
                (scope, request_key),
            ).fetchone()
        return json.loads(row["response_json"]) if row is not None else None

    def put_idempotent(
        self,
        scope: str,
        request_key: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO idempotency(scope, request_key, response_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, request_key) DO NOTHING
                """,
                (scope, request_key, json.dumps(response), utcnow().isoformat()),
            )
        return self.get_idempotent(scope, request_key) or response

    # -- durable fixed-window limiting -------------------------------------

    def consume_rate(self, bucket: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.time()
        cutoff = now - window_s
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "DELETE FROM rate_events WHERE occurred_at < ?",
                    (cutoff,),
                )
                row = self._connection.execute(
                    "SELECT COUNT(*) AS count FROM rate_events WHERE bucket = ?",
                    (bucket,),
                ).fetchone()
                if row is not None and int(row["count"]) >= limit:
                    self._connection.execute("ROLLBACK")
                    return False
                self._connection.execute(
                    "INSERT INTO rate_events(bucket, occurred_at) VALUES (?, ?)",
                    (bucket, now),
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                self._connection.execute("ROLLBACK")
                raise


def _job_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "payload": json.loads(row["payload_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

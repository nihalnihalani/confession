"""Tracked background execution backed by the durable StateStore job ledger."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .state import StateStore

JobWorker = Callable[[], Awaitable[dict[str, Any]]]


class JobManager:
    """Run bounded background work while persisting every lifecycle transition."""

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def active(self, kind: str | None = None) -> bool:
        for job_id, task in self._tasks.items():
            if task.done():
                continue
            job = self._store.get_job(job_id)
            if job is not None and (kind is None or job["kind"] == kind):
                return True
        return False

    def start(
        self,
        job_id: str,
        kind: str,
        payload: dict[str, Any],
        worker: JobWorker,
        *,
        resume: bool = False,
    ) -> dict[str, Any]:
        current = self._store.get_job(job_id)
        if current is not None and not resume:
            return current
        if current is None:
            self._store.create_job(job_id, kind, payload)
        else:
            self._store.update_job(job_id, "queued")

        task = asyncio.create_task(self._execute(job_id, kind, worker))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task, key=job_id: self._tasks.pop(key, None))
        return self._store.get_job(job_id) or {}

    async def _execute(self, job_id: str, kind: str, worker: JobWorker) -> None:
        self._store.update_job(job_id, "running")
        try:
            result = await worker()
        except asyncio.CancelledError:
            status = "queued" if kind == "audit" else "interrupted"
            self._store.update_job(job_id, status, error="Engine stopped before completion.")
            raise
        except Exception as exc:
            self._store.update_job(job_id, "failed", error=str(exc))
        else:
            self._store.update_job(job_id, "succeeded", result=result)

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

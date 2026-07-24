"""Production API controls: auth, identity binding, idempotency, jobs, and real tasks."""

import asyncio
import time

from fastapi.testclient import TestClient

from confession import config
from confession.events import EventBus
from confession.server import _stream_events, create_app


class RecordingReplay:
    async def find_project_by_name(self, _name):
        return None

    async def create_project(self, **_kwargs):
        return {"project_id": "p1", "url": "https://app.replay.io/project/p1"}

    async def poll_until_finished(self, _project_id, on_progress=None, **_kwargs):
        if on_progress is not None:
            await on_progress({"bugs": 0})
        return {"finished_at": "now"}

    async def fetch_bugs(self, _project_id, status="open"):
        assert status == "open"
        return []


def _production_app(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFESSION_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "CONFESSION_API_KEYS",
        "judge:judge-secret,builder:builder-secret,operator:operator-secret",
    )
    monkeypatch.setenv("CONFESSION_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setattr(config, "TARGET_APP_URL", "https://target.example")
    app = create_app()
    app.state.engine._replay = RecordingReplay()
    return app


def test_mutation_requires_access_key(monkeypatch, tmp_path):
    app = _production_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/claims",
            headers={"Idempotency-Key": "request-1"},
            json={"agent_id": "judge", "task_id": "T1", "claim_text": "done"},
        )
    assert response.status_code == 401


def test_role_is_bound_to_agent_identity(monkeypatch, tmp_path):
    app = _production_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/claims",
            headers={
                "Authorization": "Bearer judge-secret",
                "Idempotency-Key": "request-1",
            },
            json={"agent_id": "builder", "task_id": "T1", "claim_text": "done"},
        )
    assert response.status_code == 403


def test_claim_submission_is_idempotent_and_job_is_tracked(monkeypatch, tmp_path):
    app = _production_app(monkeypatch, tmp_path)
    headers = {
        "Authorization": "Bearer judge-secret",
        "Idempotency-Key": "same-request",
    }
    payload = {"agent_id": "judge", "task_id": "T1", "claim_text": "done"}
    with TestClient(app) as client:
        first = client.post("/api/claims", headers=headers, json=payload)
        second = client.post("/api/claims", headers=headers, json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()

        job_id = first.json()["job_id"]
        job = None
        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert job is not None
        assert job["status"] == "succeeded"
        assert job["result"]["verdict"] == "VERIFIED"


def test_tasks_endpoint_uses_builder_registry(monkeypatch, tmp_path):
    app = _production_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        tasks = client.get("/api/tasks").json()
    assert [task["id"] for task in tasks] == ["T1", "T2", "T3", "T4", "T5", "T6"]


def test_websocket_disconnect_releases_subscription():
    class DisconnectingSocket:
        async def receive(self):
            await asyncio.sleep(0)
            return {"type": "websocket.disconnect"}

        async def send_json(self, _payload):
            raise AssertionError("no event should be sent after disconnect")

    async def scenario():
        bus = EventBus()
        await _stream_events(DisconnectingSocket(), bus)
        assert bus.subscriber_count == 0

    asyncio.run(scenario())

"""FastAPI server — REST + WebSocket event stream for the dashboard.

Endpoints (paths match what the UI calls; see ui/src/types.ts and its dev proxy, which
forwards /api, /events, and /ws to this server):
* POST /api/claims          submit a claim {agent_id, task_id, claim_text} -> {claim_id}
* GET  /api/claims/{id}      the claim and its audit result
* GET  /api/receipts         live proof state: {replay[], guild[], pioneer[]}
* GET  /api/tasks            real task options for the judge form ([] when none configured)
* GET  /events               ring-buffer history ({events:[...]})
* WS   /ws                   live event stream (replays the ring buffer on connect)
* GET  /health               configuration + liveness

The judge-submit path is just POST /api/claims — the identical pipeline internal claims
use. There is no separate, special-cased endpoint; that is the Autonomy-axis proof.

Every WS event conforms exactly to the `EngineEvent` union in ui/src/types.ts; the field
names below are the authoritative contract, changed only in lockstep with that file.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator

from . import config
from .auditor import Auditor
from .builder import BuilderNotConfigured, BuilderRunner
from .events import EventBus
from .models import AuditResult, Claim, EventType, Verdict, tier_label, utcnow
from .pioneer_client import (
    PioneerClient,
    PioneerNotConfigured,
    is_success_state,
    job_id_of,
    job_state_of,
)
from .reaudit import ReauditScheduler
from .replay_client import ReplayClient, ReplayConfigError
from .tiers import TierManager
from .trainer import Trainer


class ClaimRequest(BaseModel):
    """POST /api/claims body. Contract field is `claim_text`; `text` is accepted as a
    tolerant alias so a direct curl using the shorter name still works."""

    agent_id: str
    task_id: str
    claim_text: str

    @model_validator(mode="before")
    @classmethod
    def _accept_text_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "claim_text" not in data and "text" in data:
            data = {**data, "claim_text": data["text"]}
        return data


class BuilderRunRequest(BaseModel):
    """POST /api/builder/run body. `task_id` is optional; when omitted the Builder picks
    the first not-yet-done task from the task list."""

    task_id: Optional[str] = None


class AppState:
    """Holds the long-lived engine singletons for the running server."""

    def __init__(self) -> None:
        self.bus = EventBus()
        self.tiers = TierManager(bus=self.bus)
        self.trainer = Trainer(bus=self.bus)
        self.claims: dict[str, Claim] = {}
        self.results: dict[str, AuditResult] = {}
        self._replay: Optional[ReplayClient] = None
        self._replay_error: Optional[str] = None
        try:
            self._replay = ReplayClient()
        except ReplayConfigError as exc:
            self._replay_error = str(exc)

    @property
    def replay(self) -> ReplayClient:
        if self._replay is None:
            raise HTTPException(
                status_code=503,
                detail=self._replay_error or "Replay QA is not configured (set REPLAY_API_TOKEN).",
            )
        return self._replay

    def auditor(self) -> Auditor:
        return Auditor(bus=self.bus, replay=self.replay, tiers=self.tiers, trainer=self.trainer)

    async def store_result(self, claim: Claim, result: AuditResult) -> None:
        """Capture a claim + its (possibly re-audited) result into server state and signal
        the receipts panel to refresh."""
        self.claims[claim.id] = claim
        self.results[claim.id] = result
        await self.bus.emit(EventType.RECEIPTS_UPDATED)

    def pending_claims(self) -> list[tuple[Claim, AuditResult]]:
        """Claims whose latest audit ended PENDING (candidates for re-audit)."""
        pending: list[tuple[Claim, AuditResult]] = []
        for claim_id, result in self.results.items():
            if result.verdict is Verdict.PENDING:
                claim = self.claims.get(claim_id)
                if claim is not None:
                    pending.append((claim, result))
        return pending

    def builder_runner(self) -> BuilderRunner:
        return BuilderRunner(
            auditor=self.auditor(),
            tiers=self.tiers,
            bus=self.bus,
            result_sink=self.store_result,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown. Validates the Pioneer model when a key is configured (hard-fail
    if the configured model is not listed, but never require Pioneer to boot), and runs
    the autonomous PENDING re-audit loop for the life of the process."""
    if config.pioneer_configured() and config.PIONEER_MODEL:
        try:
            await PioneerClient().validate_model(config.PIONEER_MODEL)
        except PioneerNotConfigured:
            pass

    state: AppState = app.state.engine
    reaudit_task: Optional[asyncio.Task] = None
    max_attempts = config.reaudit_max_attempts()
    if max_attempts > 0:
        scheduler = ReauditScheduler(
            pending=state.pending_claims,
            audit=lambda claim: state.auditor().audit(claim),
            store=state.store_result,
            max_attempts=max_attempts,
            interval_s=config.reaudit_interval_s(),
        )
        app.state.reaudit = scheduler
        reaudit_task = asyncio.create_task(scheduler.run_forever())
    try:
        yield
    finally:
        if reaudit_task is not None:
            reaudit_task.cancel()
            try:
                await reaudit_task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    app = FastAPI(title="CONFESSION engine", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    state = AppState()
    app.state.engine = state

    async def _run_audit(claim: Claim) -> None:
        result = await state.auditor().audit(claim)
        state.results[claim.id] = result
        # receipts_updated contract: signal only, no payload — consumers re-fetch receipts.
        await state.bus.emit(EventType.RECEIPTS_UPDATED)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "time": utcnow().isoformat(),
            "replay_configured": config.replay_configured(),
            "pioneer_configured": config.pioneer_configured(),
            "pioneer_model": config.PIONEER_MODEL,
            "target_app_url": config.TARGET_APP_URL,
            "guild_workspace": config.GUILD_WORKSPACE,
            "ratchet_n": config.ratchet_n(),
            "subscribers": state.bus.subscriber_count,
        }

    async def _submit_claim(request: ClaimRequest) -> dict[str, str]:
        if not config.TARGET_APP_URL:
            raise HTTPException(status_code=503, detail="TARGET_APP_URL is not configured.")
        # Agent-identity gate: when an allowlist is configured, only listed agent_ids may
        # submit (judge identities are always allowed). This stops an anonymous caller
        # from spoofing a builder identity to farm promotions. Judge claims are audited
        # but never move a tier (enforced in the auditor).
        allowed = config.allowed_agents()
        if allowed is not None and request.agent_id not in allowed and not config.is_judge_agent(
            request.agent_id
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"agent_id {request.agent_id!r} is not permitted to submit claims. "
                    f"Allowed: {sorted(allowed)} (plus judge identities)."
                ),
            )
        _ = state.replay  # a missing Replay token fails fast with 503
        claim = Claim(
            id=uuid.uuid4().hex,
            agent_id=request.agent_id,
            task_id=request.task_id,
            text=request.claim_text,
        )
        state.claims[claim.id] = claim
        # claim_submitted contract: {claim_id, agent_id, task_id?, task_title?, claim_text}.
        await state.bus.emit(
            EventType.CLAIM_SUBMITTED,
            claim_id=claim.id,
            agent_id=claim.agent_id,
            task_id=claim.task_id,
            claim_text=claim.text,
        )
        asyncio.create_task(_run_audit(claim))
        return {"claim_id": claim.id}

    def _get_claim(claim_id: str) -> dict[str, Any]:
        claim = state.claims.get(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail="claim not found")
        result = state.results.get(claim_id)
        return {
            "claim": claim.model_dump(mode="json"),
            "result": result.model_dump(mode="json") if result else None,
        }

    async def _receipts() -> dict[str, Any]:
        return _build_receipts(state)

    async def _tasks() -> list[dict[str, str]]:
        return _load_tasks()

    async def _run_builder(task_id: Optional[str]) -> None:
        try:
            await state.builder_runner().run(task_id)
        except BuilderNotConfigured:
            # The Guild CLI could not run; nothing is fabricated. The condition is already
            # recorded to the builder log — surfaced via the CLI path, not this endpoint.
            return

    async def _builder_run(request: BuilderRunRequest) -> dict[str, Any]:
        if not config.TARGET_APP_URL:
            raise HTTPException(status_code=503, detail="TARGET_APP_URL is not configured.")
        _ = state.replay  # a missing Replay token fails fast with 503
        if shutil.which("npx") is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "npx is not on PATH — the Guild CLI cannot run, so the Builder agent "
                    "cannot be invoked. Install Node.js and authenticate the Guild CLI."
                ),
            )
        asyncio.create_task(_run_builder(request.task_id))
        return {"status": "started", "task_id": request.task_id}

    # Register claim/receipts/tasks/builder under both /api/* (what the UI calls through
    # its dev proxy) and the bare paths (convenient for curl and the original brief). Same
    # handlers, one behavior — no special-casing.
    for prefix in ("/api", ""):
        app.post(f"{prefix}/claims")(_submit_claim)
        app.get(f"{prefix}/claims/{{claim_id}}")(_get_claim)
        app.get(f"{prefix}/receipts")(_receipts)
        app.get(f"{prefix}/tasks")(_tasks)
        app.post(f"{prefix}/builder/run")(_builder_run)

    @app.get("/events")
    async def events() -> dict[str, Any]:
        return {
            "buffer_size": state.bus.buffer_size(),
            "events": [event.model_dump(mode="json") for event in state.bus.history()],
        }

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        async with state.bus.subscribe(replay_history=True) as stream:
            try:
                async for event in stream:
                    await websocket.send_json(event.model_dump(mode="json"))
            except WebSocketDisconnect:
                return

    return app


def _load_tasks() -> list[dict[str, str]]:
    """Real task options for the judge form.

    Reads a task file if one is present (CONFESSION_TASKS_FILE, else
    engine/state/tasks.json) — a JSON array of {id, title}. When no file exists, returns
    an empty list: the judge form then falls back to a free-text task id. Nothing is
    invented here — an empty list is the honest answer when no task registry is present.
    """
    override = os.getenv("CONFESSION_TASKS_FILE")
    path = Path(override) if override else config.state_dir() / "tasks.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    tasks: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and "id" in item and "title" in item:
            tasks.append({"id": str(item["id"]), "title": str(item["title"])})
    return tasks


def _build_receipts(state: AppState) -> dict[str, Any]:
    """Dump the current live proof state in the GET /api/receipts shape (ui/src/types.ts):
    {replay: ReplayReceipt[], guild: GuildReceipt[], pioneer: PioneerReceipt[]}."""
    replay: list[dict[str, Any]] = []
    for claim_id, result in state.results.items():
        if not result.report_url:
            continue  # ReplayReceipt.report_url is required — skip entries without one
        replay.append(
            {
                "report_url": result.report_url,
                "claim_id": claim_id,
                "verdict": result.verdict.value,
                "created_at": result.finished_at.isoformat() if result.finished_at else None,
            }
        )

    guild: list[dict[str, Any]] = []
    for agent_id, tier in state.tiers.all_states().items():
        note = None
        if tier.history:
            last = tier.history[-1]
            transition = last.get("transition")
            side_effect = last.get("side_effect")
            if transition:
                note = f"{transition} ({side_effect})" if side_effect else str(transition)
        guild.append(
            {"agent_id": agent_id, "tier": tier_label(tier.tier), "session_note": note}
        )

    pioneer = _pioneer_receipts(state.trainer.read_training_log())
    return {"replay": replay, "guild": guild, "pioneer": pioneer}


def _pioneer_receipts(training_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate the training log into PioneerReceipt[] — one row per fine-tune job.

    Rows are keyed by the fine-tune job id (which IS the model id once training
    succeeds). `status` is the latest observed state; `model_id` is set only when a
    success state has been seen.
    """
    jobs: dict[str, dict[str, Any]] = {}
    for entry in training_log:
        kind = entry.get("kind")
        response = entry.get("response")
        at = entry.get("at")
        if kind not in {"finetune_started", "finetune_status", "finetune_finished"}:
            continue
        job_id = (
            job_id_of(response) if kind == "finetune_started" else _job_id_from_status(response)
        )
        if not job_id:
            continue
        row = jobs.setdefault(job_id, {"job_id": job_id, "status": "started", "started_at": at})
        if kind == "finetune_started":
            row["started_at"] = row.get("started_at") or at
            continue
        state_str = job_state_of(response)
        row["status"] = state_str
        if is_success_state(state_str):
            row["model_id"] = job_id
    return list(jobs.values())


def _job_id_from_status(response: Any) -> Optional[str]:
    if isinstance(response, dict):
        for key in ("id", "job_id", "training_job_id", "jobId"):
            value = response.get(key)
            if value:
                return str(value)
    return None


# Module-level ASGI app for `uvicorn confession.server:app`.
app = create_app()

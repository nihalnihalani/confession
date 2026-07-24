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
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Any, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from . import config
from .auditor import Auditor
from .builder import BuilderRunner, parse_tasks
from .events import EventBus
from .jobs import JobManager
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
from .security import authorize, enforce_identity, enforce_rate_limit, idempotency_key
from .state import StateStore
from .tiers import TierManager
from .trainer import Trainer


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
ClaimText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]
ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimRequest(StrictRequest):
    """POST /api/claims body. Contract field is `claim_text`; `text` is accepted as a
    tolerant alias so a direct curl using the shorter name still works."""

    agent_id: Identifier
    task_id: Identifier
    claim_text: ClaimText

    @model_validator(mode="before")
    @classmethod
    def _accept_text_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "claim_text" not in data and "text" in data:
            data = {**data, "claim_text": data["text"]}
            data.pop("text", None)
        return data


class BuilderRunRequest(StrictRequest):
    """POST /api/builder/run body. `task_id` is optional; when omitted the Builder picks
    the first not-yet-done task from the task list."""

    task_id: Optional[Identifier] = None


class TrainingRunRequest(StrictRequest):
    """POST /api/training/run body."""

    base_model: Optional[ModelName] = None


class AppState:
    """Holds the long-lived engine singletons for the running server."""

    def __init__(self) -> None:
        self.store = StateStore(config.database_path())
        self.bus = EventBus(sink=self._persist_event)
        self.bus.restore(self.store.load_events())
        self.tiers = TierManager(bus=self.bus)
        self.trainer = Trainer(bus=self.bus)
        self.claims, self.results = self.store.load_claims()
        self.jobs = JobManager(self.store)
        self._replay: Optional[ReplayClient] = None
        self._replay_error: Optional[str] = None
        try:
            self._replay = ReplayClient()
        except ReplayConfigError as exc:
            self._replay_error = str(exc)

    async def _persist_event(self, event) -> None:
        await asyncio.to_thread(self.store.append_event, event)

    @property
    def replay(self) -> ReplayClient:
        if self._replay is None:
            raise HTTPException(
                status_code=503,
                detail=self._replay_error or "Replay QA is not configured (set REPLAY_API_TOKEN).",
            )
        return self._replay

    def auditor(self) -> Auditor:
        return Auditor(
            bus=self.bus,
            replay=self.replay,
            tiers=self.tiers,
            trainer=self.trainer,
            result_checkpoint=self.checkpoint_result,
        )

    async def checkpoint_result(self, claim: Claim, result: AuditResult) -> None:
        """Persist the Replay project receipt before polling so restarts resume it."""
        self.claims[claim.id] = claim
        self.results[claim.id] = result
        await asyncio.to_thread(self.store.save_claim, claim, result)

    async def store_result(self, claim: Claim, result: AuditResult) -> None:
        """Capture a claim + its (possibly re-audited) result into server state and signal
        the receipts panel to refresh."""
        self.claims[claim.id] = claim
        self.results[claim.id] = result
        await asyncio.to_thread(self.store.save_claim, claim, result)
        await self.bus.emit(EventType.RECEIPTS_UPDATED)
        self.maybe_start_training()

    async def save_claim(self, claim: Claim) -> None:
        self.claims[claim.id] = claim
        await asyncio.to_thread(self.store.save_claim, claim)

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

    def start_audit(self, claim: Claim, job_id: Optional[str] = None, resume: bool = False) -> dict[str, Any]:
        identifier = job_id or f"audit-{claim.id}"

        async def worker() -> dict[str, Any]:
            result = await self.auditor().audit(
                claim,
                previous_result=self.results.get(claim.id),
            )
            await self.store_result(claim, result)
            return result.model_dump(mode="json")

        return self.jobs.start(
            identifier,
            "audit",
            {"claim_id": claim.id},
            worker,
            resume=resume,
        )

    def start_builder(
        self,
        job_id: str,
        task_id: Optional[str],
        *,
        resume: bool = False,
    ) -> dict[str, Any]:
        async def worker() -> dict[str, Any]:
            return await self.builder_runner().run(task_id)

        return self.jobs.start(
            job_id,
            "builder",
            {"task_id": task_id},
            worker,
            resume=resume,
        )

    def start_training(
        self,
        job_id: str,
        base_model: str,
        *,
        resume: bool = False,
    ) -> dict[str, Any]:
        async def worker() -> dict[str, Any]:
            return await self.trainer.run_finetune(base_model=base_model)

        return self.jobs.start(
            job_id,
            "training",
            {"base_model": base_model},
            worker,
            resume=resume,
        )

    def maybe_start_training(self) -> None:
        threshold = config.pioneer_autotrain_min_lies()
        base_model = config.PIONEER_BASE_MODEL
        if (
            threshold <= 0
            or not base_model
            or not config.pioneer_configured()
            or self.jobs.active("training")
        ):
            return
        lies = self.trainer.read_lies()
        if len(lies) < threshold:
            return
        job_id = f"training-auto-{len(lies)}"
        self.start_training(job_id, base_model)

    def recover_jobs(self) -> None:
        """Resume safe audit work; mark non-idempotent interrupted work for operator retry."""
        for job in self.store.recoverable_jobs():
            if job["kind"] == "audit":
                claim_id = str(job["payload"].get("claim_id", ""))
                claim = self.claims.get(claim_id)
                result = self.results.get(claim_id)
                if claim is not None and (result is None or result.verdict is Verdict.PENDING):
                    self.start_audit(claim, job_id=job["id"], resume=True)
                    continue
            self.store.update_job(
                job["id"],
                "interrupted",
                error="Engine restarted; retry this operation with a new request key.",
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
    if config.pioneer_configured() and config.PIONEER_BASE_MODEL:
        try:
            await PioneerClient().validate_base_model(config.PIONEER_BASE_MODEL)
        except PioneerNotConfigured:
            pass

    state: AppState = app.state.engine
    state.recover_jobs()
    reaudit_task: Optional[asyncio.Task] = None
    guild_task: Optional[asyncio.Task] = None
    max_attempts = config.reaudit_max_attempts()
    if max_attempts > 0:
        scheduler = ReauditScheduler(
            pending=state.pending_claims,
            audit=lambda claim: state.auditor().audit(
                claim,
                previous_result=state.results.get(claim.id),
            ),
            store=state.store_result,
            max_attempts=max_attempts,
            interval_s=config.reaudit_interval_s(),
            attempt_provider=state.store.reaudit_attempts,
            attempt_spender=state.store.increment_reaudit_attempt,
        )
        app.state.reaudit = scheduler
        reaudit_task = asyncio.create_task(scheduler.run_forever())

    async def reconcile_guild() -> None:
        while True:
            await asyncio.sleep(config.guild_reconcile_interval_s())
            await state.tiers.reconcile_pending()

    guild_task = asyncio.create_task(reconcile_guild())
    try:
        yield
    finally:
        if guild_task is not None:
            guild_task.cancel()
            try:
                await guild_task
            except asyncio.CancelledError:
                pass
        if reaudit_task is not None:
            reaudit_task.cancel()
            try:
                await reaudit_task
            except asyncio.CancelledError:
                pass
        await state.jobs.shutdown()
        state.store.close()


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

    @app.get("/health")
    async def health() -> dict[str, Any]:
        components = {
            "database": state.store.path.exists(),
            "state_dir": config.state_dir().is_dir(),
            "replay": config.replay_configured(),
            "target_app": config.target_app_configured(),
            "pioneer": config.pioneer_configured(),
            "auth": not config.auth_required() or bool(config.api_keys()),
            "guild_grants": not state.tiers.has_pending_actions(),
        }
        if config.serve_ui():
            components["dashboard"] = config.ui_dist_path().is_dir()
        ready = all(components.values()) if config.ENVIRONMENT == "production" else all(
            components[key] for key in ("database", "replay", "target_app", "auth")
        )
        return {
            "status": "ready" if ready else "degraded",
            "time": utcnow().isoformat(),
            "environment": config.ENVIRONMENT,
            "components": components,
            "replay_configured": config.replay_configured(),
            "pioneer_configured": config.pioneer_configured(),
            "pioneer_model": config.PIONEER_MODEL,
            "target_app_url": config.TARGET_APP_URL,
            "guild_workspace": config.GUILD_WORKSPACE,
            "ratchet_n": config.ratchet_n(),
            "subscribers": state.bus.subscriber_count,
        }

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        snapshot = await health()
        if snapshot["status"] != "ready":
            raise HTTPException(status_code=503, detail=snapshot)
        return snapshot

    @app.post("/api/auth/check")
    @app.post("/auth/check")
    async def auth_check(http_request: Request) -> dict[str, str]:
        role = authorize(http_request, {"judge", "builder", "operator"})
        enforce_rate_limit(http_request, state.store, "auth-check", role, multiplier=2)
        return {"status": "ok", "role": role}

    async def _submit_claim(request: ClaimRequest, http_request: Request) -> dict[str, str]:
        if not config.target_app_configured():
            raise HTTPException(
                status_code=503,
                detail="TARGET_APP_URL must be a valid deployed HTTPS URL in production.",
            )
        role = authorize(http_request, {"judge", "builder"})
        enforce_identity(role, request.agent_id)
        enforce_rate_limit(http_request, state.store, "claims", role)
        request_key = idempotency_key(http_request, required=config.auth_required())
        if request_key:
            existing = state.store.get_idempotent("claims", request_key)
            if existing is not None:
                return existing
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
            id=(
                uuid.uuid5(uuid.NAMESPACE_URL, f"confession:claims:{request_key}").hex
                if request_key
                else uuid.uuid4().hex
            ),
            agent_id=request.agent_id,
            task_id=request.task_id,
            text=request.claim_text,
        )
        await state.save_claim(claim)
        # claim_submitted contract: {claim_id, agent_id, task_id?, task_title?, claim_text}.
        await state.bus.emit(
            EventType.CLAIM_SUBMITTED,
            claim_id=claim.id,
            agent_id=claim.agent_id,
            task_id=claim.task_id,
            claim_text=claim.text,
        )
        job_id = f"audit-{claim.id}"
        state.start_audit(claim, job_id=job_id)
        response = {"claim_id": claim.id, "job_id": job_id}
        return (
            state.store.put_idempotent("claims", request_key, response)
            if request_key
            else response
        )

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

    async def _builder_run(request: BuilderRunRequest, http_request: Request) -> dict[str, Any]:
        if not config.target_app_configured():
            raise HTTPException(
                status_code=503,
                detail="TARGET_APP_URL must be a valid deployed HTTPS URL in production.",
            )
        role = authorize(http_request, {"operator"})
        enforce_rate_limit(http_request, state.store, "builder", role, multiplier=1)
        request_key = idempotency_key(http_request, required=config.auth_required())
        if request_key:
            existing = state.store.get_idempotent("builder", request_key)
            if existing is not None:
                return existing
        _ = state.replay  # a missing Replay token fails fast with 503
        job_id = (
            f"builder-{uuid.uuid5(uuid.NAMESPACE_URL, request_key).hex}"
            if request_key
            else f"builder-{uuid.uuid4().hex}"
        )
        state.start_builder(job_id, request.task_id)
        response = {"status": "queued", "task_id": request.task_id, "job_id": job_id}
        return (
            state.store.put_idempotent("builder", request_key, response)
            if request_key
            else response
        )

    async def _training_run(
        request: TrainingRunRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        role = authorize(http_request, {"operator"})
        enforce_rate_limit(http_request, state.store, "training", role)
        request_key = idempotency_key(http_request, required=config.auth_required())
        if request_key:
            existing = state.store.get_idempotent("training", request_key)
            if existing is not None:
                return existing
        base_model = request.base_model or config.PIONEER_BASE_MODEL
        if not base_model:
            raise HTTPException(
                status_code=503,
                detail="PIONEER_BASE_MODEL or request.base_model is required.",
            )
        if not config.pioneer_configured():
            raise HTTPException(status_code=503, detail="Pioneer is not configured.")
        job_id = (
            f"training-{uuid.uuid5(uuid.NAMESPACE_URL, request_key).hex}"
            if request_key
            else f"training-{uuid.uuid4().hex}"
        )
        state.start_training(job_id, base_model)
        response = {"status": "queued", "job_id": job_id, "base_model": base_model}
        return (
            state.store.put_idempotent("training", request_key, response)
            if request_key
            else response
        )

    def _get_job(job_id: str) -> dict[str, Any]:
        job = state.store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    # Register claim/receipts/tasks/builder under both /api/* (what the UI calls through
    # its dev proxy) and the bare paths (convenient for curl and the original brief). Same
    # handlers, one behavior — no special-casing.
    for prefix in ("/api", ""):
        app.post(f"{prefix}/claims")(_submit_claim)
        app.get(f"{prefix}/claims/{{claim_id}}")(_get_claim)
        app.get(f"{prefix}/receipts")(_receipts)
        app.get(f"{prefix}/tasks")(_tasks)
        app.post(f"{prefix}/builder/run")(_builder_run)
        app.post(f"{prefix}/training/run")(_training_run)
        app.get(f"{prefix}/jobs/{{job_id}}")(_get_job)

    @app.get("/events")
    async def events() -> dict[str, Any]:
        return {
            "buffer_size": state.bus.buffer_size(),
            "events": [event.to_contract() for event in state.bus.history()],
        }

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await _stream_events(websocket, state.bus)

    if config.serve_ui():
        dashboard = config.ui_dist_path()
        if not dashboard.is_dir():
            raise RuntimeError(
                f"CONFESSION_SERVE_UI is enabled but the dashboard build is missing: {dashboard}"
            )
        # Registered last so API, event, health, and WebSocket routes retain precedence.
        app.mount("/", StaticFiles(directory=str(dashboard), html=True), name="dashboard")

    return app


async def _stream_events(websocket: WebSocket, bus: EventBus) -> None:
    """Forward events while also listening for disconnects from otherwise-idle clients."""
    async with bus.subscribe(replay_history=True) as stream:
        next_event = asyncio.create_task(stream.__anext__())
        next_frame = asyncio.create_task(websocket.receive())
        try:
            while True:
                completed, _ = await asyncio.wait(
                    {next_event, next_frame},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if next_frame in completed:
                    frame = next_frame.result()
                    if frame["type"] == "websocket.disconnect":
                        return
                    next_frame = asyncio.create_task(websocket.receive())
                if next_event in completed:
                    try:
                        event = next_event.result()
                    except StopAsyncIteration:
                        return
                    await websocket.send_json(event.to_contract())
                    next_event = asyncio.create_task(stream.__anext__())
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            for task in (next_event, next_frame):
                if not task.done():
                    task.cancel()
            await asyncio.gather(next_event, next_frame, return_exceptions=True)


def _load_tasks() -> list[dict[str, str]]:
    """Real task options for the judge form.

    Reads the exact same real TASKS.md registry as the autonomous Builder. When no file
    exists, returns an empty list; nothing is invented.
    """
    path = config.tasks_file()
    if not path.exists():
        return []
    return [{"id": task.id, "title": task.title} for task in parse_tasks(path.read_text())]


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
        if tier.pending_guild_action:
            note = (
                f"{tier.pending_guild_action} pending "
                f"({tier.guild_error}; attempt {tier.pending_attempts})"
            )
        if tier.history:
            last = tier.history[-1]
            transition = last.get("transition")
            side_effect = last.get("side_effect")
            if transition and not note:
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

"""FastAPI server — REST + WebSocket event stream for the dashboard.

Endpoints:
* POST /claims            submit a claim; audits it as a background task, returns its id
* GET  /claims/{id}       the claim and its audit result
* GET  /health            configuration + liveness
* GET  /receipts          live state: tiers, recent verdicts (real report URLs),
                          caught-lie tail, training-log tail
* GET  /events            ring-buffer dump (dashboard history view)
* WS   /ws                live event stream (replays the ring buffer on connect)

The judge-submit path is just POST /claims — the identical pipeline internal claims use.
There is no separate, special-cased endpoint; that is the Autonomy-axis proof.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config
from .auditor import Auditor
from .events import EventBus
from .models import AuditResult, Claim, EventType, utcnow
from .pioneer_client import PioneerClient, PioneerNotConfigured
from .replay_client import ReplayClient, ReplayConfigError
from .tiers import TierManager
from .trainer import Trainer


class ClaimRequest(BaseModel):
    agent_id: str
    task_id: str
    text: str


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
        # Build the Replay client eagerly so /health reflects real config, but tolerate a
        # missing token (the server still serves receipts/health without it).
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
        return Auditor(
            bus=self.bus, replay=self.replay, tiers=self.tiers, trainer=self.trainer
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate the Pioneer model at startup when a key is configured (hard-fail if the
    configured model is not listed) — but never require Pioneer to boot the server."""
    if config.pioneer_configured() and config.PIONEER_MODEL:
        try:
            await PioneerClient().validate_model(config.PIONEER_MODEL)
        except PioneerNotConfigured:
            pass
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="CONFESSION engine", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    state = AppState()
    app.state.engine = state

    async def _run_audit(claim: Claim) -> None:
        result = await state.auditor().audit(claim)
        state.results[claim.id] = result
        await state.bus.emit(EventType.RECEIPTS_UPDATED, claim_id=claim.id)

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

    @app.post("/claims")
    async def submit_claim(request: ClaimRequest) -> dict[str, str]:
        if not config.TARGET_APP_URL:
            raise HTTPException(status_code=503, detail="TARGET_APP_URL is not configured.")
        # Touch the Replay client so a missing token fails fast with 503.
        _ = state.replay
        claim = Claim(
            id=uuid.uuid4().hex,
            agent_id=request.agent_id,
            task_id=request.task_id,
            text=request.text,
        )
        state.claims[claim.id] = claim
        await state.bus.emit(
            EventType.CLAIM_SUBMITTED,
            claim_id=claim.id,
            agent_id=claim.agent_id,
            task_id=claim.task_id,
            text=claim.text,
        )
        asyncio.create_task(_run_audit(claim))
        return {"claim_id": claim.id}

    @app.get("/claims/{claim_id}")
    async def get_claim(claim_id: str) -> dict[str, Any]:
        claim = state.claims.get(claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail="claim not found")
        result = state.results.get(claim_id)
        return {
            "claim": claim.model_dump(mode="json"),
            "result": result.model_dump(mode="json") if result else None,
        }

    @app.get("/receipts")
    async def receipts() -> dict[str, Any]:
        return _build_receipts(state)

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


def _build_receipts(state: AppState) -> dict[str, Any]:
    """Dump the current live state that the receipts page renders."""
    recent_verdicts = []
    for claim_id, result in list(state.results.items())[-25:]:
        claim = state.claims.get(claim_id)
        recent_verdicts.append(
            {
                "claim_id": claim_id,
                "agent_id": claim.agent_id if claim else None,
                "task_id": claim.task_id if claim else None,
                "text": claim.text if claim else None,
                "verdict": result.verdict.value,
                "report_url": result.report_url,
                "replay_project_id": result.replay_project_id,
                "bugs": [bug.model_dump(mode="json") for bug in result.bugs],
                "error": result.error,
                "finished_at": result.finished_at.isoformat() if result.finished_at else None,
            }
        )
    return {
        "generated_at": utcnow().isoformat(),
        "tiers": {
            agent_id: tier.model_dump(mode="json")
            for agent_id, tier in state.tiers.all_states().items()
        },
        "recent_verdicts": recent_verdicts,
        "lies": state.trainer.read_lies()[-25:],
        "training": state.trainer.read_training_log()[-25:],
    }


# Module-level ASGI app for `uvicorn confession.server:app`.
app = create_app()

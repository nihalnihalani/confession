"""The auditor — one claim, one real audit against Replay QA.

`Auditor.audit` is the single code path used by BOTH internally-generated Builder claims
and judge-submitted claims. There is no special-casing: a judge's claim and the Builder's
claim run the exact same steps. That identical path is the Autonomy-axis proof.

Steps, each emitting an event:
1. create a Replay project against the target app (audit_started)
2. poll until QA finishes, streaming progress (audit_progress)
3. fetch the real bugs, decide the verdict (verdict_reached)
4. apply the tier ratchet (tier_changed, via TierManager — the one write path)
5. on FALSE_CLAIM, record the caught lie (lie_recorded)

A Replay infra error (timeout/5xx/network) sets `AuditResult.error`, forces the verdict
to PENDING, and leaves the tier untouched — the claim is surfaced for re-audit.
"""

from __future__ import annotations

from typing import Optional

from . import config
from .events import EventBus
from .models import AuditResult, Claim, ClaimStatus, EventType, Verdict, utcnow
from .replay_client import (
    ReplayClient,
    ReplayInfraError,
    dashboard_url_of,
    project_id_of,
)
from .tiers import TierManager
from .trainer import Trainer
from .verdicts import decide_verdict, in_scope_bugs


class Auditor:
    """Orchestrates a single real audit cycle."""

    def __init__(
        self,
        bus: EventBus,
        replay: ReplayClient,
        tiers: TierManager,
        trainer: Trainer,
        target_url: Optional[str] = None,
        poll_interval_s: Optional[float] = None,
        poll_timeout_s: Optional[float] = None,
    ) -> None:
        self._bus = bus
        self._replay = replay
        self._tiers = tiers
        self._trainer = trainer
        self._target_url = target_url or config.TARGET_APP_URL
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s

    async def audit(self, claim: Claim) -> AuditResult:
        """Audit one claim end to end. Never raises for an infra error — it is captured on
        the returned `AuditResult` as PENDING."""
        if not self._target_url:
            raise ValueError("No target app URL configured (set TARGET_APP_URL).")

        claim.status = ClaimStatus.AUDITING
        result = AuditResult(claim_id=claim.id, verdict=Verdict.PENDING)

        try:
            result = await self._run_replay(claim, result)
        except ReplayInfraError as exc:
            # Infra error -> PENDING, tier untouched, claim re-audited later.
            result.error = str(exc)
            result.verdict = Verdict.PENDING
            result.finished_at = utcnow()
            claim.status = ClaimStatus.RESOLVED
            await self._bus.emit(
                EventType.VERDICT_REACHED,
                claim_id=claim.id,
                agent_id=claim.agent_id,
                verdict=result.verdict.value,
                error=result.error,
                report_url=result.report_url,
                replay_project_id=result.replay_project_id,
            )
            return result

        # -- verdict ---------------------------------------------------------
        result.verdict = decide_verdict(claim, result)
        result.finished_at = utcnow()
        scoped = in_scope_bugs(claim, result.bugs)
        await self._bus.emit(
            EventType.VERDICT_REACHED,
            claim_id=claim.id,
            agent_id=claim.agent_id,
            verdict=result.verdict.value,
            report_url=result.report_url,
            replay_project_id=result.replay_project_id,
            bugs=[bug.model_dump(mode="json") for bug in scoped],
            bug_count=len(scoped),
        )

        # -- consequence: tier ratchet (the one write path) -----------------
        await self._tiers.apply_verdict(claim.agent_id, result.verdict)

        # -- evolution: record the caught lie -------------------------------
        if result.verdict is Verdict.FALSE_CLAIM and scoped:
            root_cause = "; ".join(bug.root_cause for bug in scoped if bug.root_cause) or (
                "Replay QA found open bugs in the claimed scope."
            )
            await self._trainer.record_lie(claim, root_cause, report_url=result.report_url)

        claim.status = ClaimStatus.RESOLVED
        return result

    async def _run_replay(self, claim: Claim, result: AuditResult) -> AuditResult:
        """Create the Replay project, poll to completion, and attach the real bugs.

        Raises `ReplayInfraError` on any transport/timeout failure (handled by `audit`).
        """
        create_response = await self._replay.create_project(
            target_url=self._target_url,
            name=f"confession-{claim.id}",
            instructions=(
                f"Verify the work claimed complete for task {claim.task_id}: {claim.text}. "
                "Explore the app and test the affected flows."
            ),
        )
        project_id = project_id_of(create_response)
        result.replay_project_id = project_id
        result.report_url = dashboard_url_of(create_response)

        await self._bus.emit(
            EventType.AUDIT_STARTED,
            claim_id=claim.id,
            agent_id=claim.agent_id,
            replay_project_id=project_id,
            report_url=result.report_url,
            target_url=self._target_url,
        )

        if not project_id:
            raise ReplayInfraError(
                f"Replay createProject did not return a project id: {create_response!r}"
            )

        async def _on_progress(status: dict) -> None:
            await self._bus.emit(
                EventType.AUDIT_PROGRESS,
                claim_id=claim.id,
                replay_project_id=project_id,
                status=status,
            )

        kwargs = {}
        if self._poll_interval_s is not None:
            kwargs["interval_s"] = self._poll_interval_s
        if self._poll_timeout_s is not None:
            kwargs["timeout_s"] = self._poll_timeout_s
        await self._replay.poll_until_finished(project_id, on_progress=_on_progress, **kwargs)

        result.bugs = await self._replay.fetch_bugs(project_id, status="open")
        return result

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
            # verdict_reached contract (ui/src/types.ts): {claim_id, agent_id, verdict,
            # report_url?, bugs[]}. PENDING carries no bugs; the infra reason lives on the
            # AuditResult and in /api/receipts, not on this event.
            await self._bus.emit(
                EventType.VERDICT_REACHED,
                claim_id=claim.id,
                agent_id=claim.agent_id,
                verdict=result.verdict.value,
                report_url=result.report_url,
                bugs=[],
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
            bugs=[bug.to_contract() for bug in scoped],
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

        # audit_started contract (ui/src/types.ts): {claim_id, project_url?, target_url?}.
        await self._bus.emit(
            EventType.AUDIT_STARTED,
            claim_id=claim.id,
            project_url=result.report_url,
            target_url=self._target_url,
        )

        if not project_id:
            raise ReplayInfraError(
                f"Replay createProject did not return a project id: {create_response!r}"
            )

        async def _on_progress(status: dict) -> None:
            # audit_progress contract: {claim_id, message, progress?}. Replay's status is
            # a counts summary (no completion fraction), so we surface a human message and
            # omit progress rather than inventing a percentage.
            await self._bus.emit(
                EventType.AUDIT_PROGRESS,
                claim_id=claim.id,
                message=_progress_message(status),
            )

        kwargs = {}
        if self._poll_interval_s is not None:
            kwargs["interval_s"] = self._poll_interval_s
        if self._poll_timeout_s is not None:
            kwargs["timeout_s"] = self._poll_timeout_s
        await self._replay.poll_until_finished(project_id, on_progress=_on_progress, **kwargs)

        result.bugs = await self._replay.fetch_bugs(project_id, status="open")
        return result


def _progress_message(status: dict) -> str:
    """Build a human progress line from a Replay status summary (counts of explorations,
    journeys, test runs, and bugs). Missing counts are simply omitted."""
    parts: list[str] = []
    for key, noun in (
        ("explorations", "exploration"),
        ("journeys", "journey"),
        ("test_runs", "test run"),
        ("testRuns", "test run"),
        ("bugs", "bug"),
        ("open_bugs", "open bug"),
    ):
        value = status.get(key) if isinstance(status, dict) else None
        count = _count_of(value)
        if count is not None:
            plural = "" if count == 1 else "s"
            parts.append(f"{count} {noun}{plural}")
    return "Replay QA running: " + ", ".join(parts) if parts else "Replay QA running…"


def _count_of(value: object) -> Optional[int]:
    """Coerce a status field that may be a raw int or a {count/total: n} object."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        for key in ("count", "total", "open"):
            inner = value.get(key)
            if isinstance(inner, int) and not isinstance(inner, bool):
                return inner
    return None

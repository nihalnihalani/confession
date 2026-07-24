"""Unit tests for the PENDING re-audit logic — pure eligibility and the scheduler's
bounded-retry control flow. No network: the scheduler is driven by in-memory
collaborators (a real dict of results and a small counting audit function)."""

import asyncio

from confession.models import AuditResult, Claim, Verdict
from confession.reaudit import ReauditScheduler, is_reaudit_eligible


# --- pure eligibility ------------------------------------------------------


def test_eligible_only_when_pending_and_under_budget():
    assert is_reaudit_eligible(Verdict.PENDING, 0, 3) is True
    assert is_reaudit_eligible(Verdict.PENDING, 2, 3) is True


def test_not_eligible_when_budget_spent():
    assert is_reaudit_eligible(Verdict.PENDING, 3, 3) is False
    assert is_reaudit_eligible(Verdict.PENDING, 4, 3) is False


def test_settled_verdicts_never_eligible():
    assert is_reaudit_eligible(Verdict.VERIFIED, 0, 3) is False
    assert is_reaudit_eligible(Verdict.FALSE_CLAIM, 0, 3) is False


def test_zero_budget_never_eligible():
    assert is_reaudit_eligible(Verdict.PENDING, 0, 0) is False


# --- scheduler control flow ------------------------------------------------


def _claim(cid="c1") -> Claim:
    return Claim(id=cid, task_id="t", agent_id="builder", text="done")


def test_run_once_reaudits_and_stores_flip_to_verified():
    async def scenario():
        claim = _claim()
        results = {claim.id: AuditResult(claim_id=claim.id, verdict=Verdict.PENDING)}

        async def audit(c: Claim) -> AuditResult:
            # the target recovered: this audit now returns a settled verdict
            return AuditResult(claim_id=c.id, verdict=Verdict.VERIFIED)

        async def store(c: Claim, r: AuditResult) -> None:
            results[c.id] = r

        def pending():
            return [(claim, r) for cid, r in results.items() if r.verdict is Verdict.PENDING]

        sched = ReauditScheduler(pending, audit, store, max_attempts=3, interval_s=0.01)
        count = await sched.run_once()
        assert count == 1
        assert results[claim.id].verdict is Verdict.VERIFIED
        assert sched.attempts_for(claim.id) == 1
        # now settled -> no longer eligible
        assert await sched.run_once() == 0

    asyncio.run(scenario())


def test_run_once_respects_max_attempts_when_stuck_pending():
    async def scenario():
        claim = _claim()
        results = {claim.id: AuditResult(claim_id=claim.id, verdict=Verdict.PENDING)}
        calls = {"n": 0}

        async def audit(c: Claim) -> AuditResult:
            calls["n"] += 1
            return AuditResult(claim_id=c.id, verdict=Verdict.PENDING, error="still down")

        async def store(c: Claim, r: AuditResult) -> None:
            results[c.id] = r

        def pending():
            return [(claim, r) for cid, r in results.items() if r.verdict is Verdict.PENDING]

        sched = ReauditScheduler(pending, audit, store, max_attempts=3, interval_s=0.01)
        for _ in range(5):
            await sched.run_once()
        # capped at exactly max_attempts real audits despite staying PENDING
        assert calls["n"] == 3
        assert sched.attempts_for(claim.id) == 3

    asyncio.run(scenario())


def test_run_once_survives_a_failing_audit():
    async def scenario():
        claim = _claim()
        results = {claim.id: AuditResult(claim_id=claim.id, verdict=Verdict.PENDING)}

        async def audit(c: Claim) -> AuditResult:
            raise RuntimeError("audit blew up")

        async def store(c: Claim, r: AuditResult) -> None:
            results[c.id] = r

        def pending():
            return [(claim, r) for cid, r in results.items() if r.verdict is Verdict.PENDING]

        sched = ReauditScheduler(pending, audit, store, max_attempts=2, interval_s=0.01)
        # does not raise; the claim stays PENDING and the attempt is still counted
        assert await sched.run_once() == 0
        assert results[claim.id].verdict is Verdict.PENDING
        assert sched.attempts_for(claim.id) == 1

    asyncio.run(scenario())

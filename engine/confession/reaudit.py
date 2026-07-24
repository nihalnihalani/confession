"""Autonomous re-audit of PENDING claims.

A claim ends PENDING only on a Replay infra condition (timeout/5xx/network) — never as a
verdict. CLAUDE.md says such a claim is "re-audited later"; this module is the later. A
background loop periodically re-runs the full audit pipeline on every still-PENDING claim
(re-emitting audit_started/verdict_reached on the SAME claim_id, which the UI reducer
folds by id), up to a bounded number of attempts so a permanently-unreachable target does
not retry forever.

`is_reaudit_eligible` is pure and exhaustively unit-tested; `ReauditScheduler` wires it to
the running server's state with real collaborators (no network in the scheduler itself —
it delegates to the same auditor every other claim uses).
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from .models import AuditResult, Claim, Verdict

# Types for the scheduler's collaborators, kept explicit for readability.
PendingProvider = Callable[[], list[tuple[Claim, AuditResult]]]
AuditFn = Callable[[Claim], Awaitable[AuditResult]]
StoreFn = Callable[[Claim, AuditResult], Awaitable[None]]
AttemptProvider = Callable[[str], int]
AttemptSpender = Callable[[str, int], Optional[int]]


def is_reaudit_eligible(verdict: Verdict, attempts: int, max_attempts: int) -> bool:
    """A claim is eligible for another audit only while it is PENDING and has not yet used
    its attempt budget. Any settled verdict (VERIFIED/FALSE_CLAIM) is never re-audited."""
    return verdict is Verdict.PENDING and attempts < max_attempts


class ReauditScheduler:
    """Periodically re-audits still-PENDING claims, bounded per claim by `max_attempts`."""

    def __init__(
        self,
        pending: PendingProvider,
        audit: AuditFn,
        store: StoreFn,
        max_attempts: int,
        interval_s: float,
        attempt_provider: Optional[AttemptProvider] = None,
        attempt_spender: Optional[AttemptSpender] = None,
    ) -> None:
        self._pending = pending
        self._audit = audit
        self._store = store
        self._max_attempts = max_attempts
        self._interval_s = interval_s
        self._attempts: dict[str, int] = {}
        self._attempt_provider = attempt_provider
        self._attempt_spender = attempt_spender

    def attempts_for(self, claim_id: str) -> int:
        if self._attempt_provider is not None:
            return self._attempt_provider(claim_id)
        return self._attempts.get(claim_id, 0)

    async def run_once(self) -> int:
        """Re-audit every eligible PENDING claim once. Returns how many were re-audited.

        Each claim's attempt count is checked before its budget is spent, so with
        `max_attempts=N` a claim is re-audited at most N times. A per-claim failure is
        swallowed so one bad claim never blocks the rest of the sweep.
        """
        reaudited = 0
        for claim, result in self._pending():
            attempts = self.attempts_for(claim.id)
            if not is_reaudit_eligible(result.verdict, attempts, self._max_attempts):
                continue
            if self._attempt_spender is not None:
                if self._attempt_spender(claim.id, self._max_attempts) is None:
                    continue
            else:
                self._attempts[claim.id] = attempts + 1
            try:
                new_result = await self._audit(claim)
                await self._store(claim, new_result)
                reaudited += 1
            except Exception:
                # Never let one claim's failure kill the sweep; it stays PENDING and is
                # retried next tick until its attempt budget is spent.
                continue
        return reaudited

    async def run_forever(self, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> None:
        """Loop forever: sleep, then run one sweep. Cancels cleanly; other errors are
        contained so the loop itself never dies."""
        while True:
            await sleep(self._interval_s)
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

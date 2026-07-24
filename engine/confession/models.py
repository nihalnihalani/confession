"""Pydantic v2 domain models and the typed event contract.

These types are the vocabulary shared by every layer: the Replay client produces
`BugFinding`s, the verdict engine consumes a `Claim` + `AuditResult` and emits a
`Verdict`, the tier ratchet advances a `TierState`, and the event bus streams `Event`s
to the dashboard over the WebSocket.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now — every timestamp in the system uses this."""
    return datetime.now(timezone.utc)


class Verdict(str, Enum):
    """The only three audit outcomes. There is no fourth state and no manual override.

    * VERIFIED    — Replay explored the app and found zero open bugs in the claimed scope.
    * FALSE_CLAIM — Replay found the claimed-done work broken (open bugs in scope).
    * PENDING     — the audit is running, or Replay had an infra error (timeout/5xx).
                    A PENDING claim never changes an agent's tier.
    """

    VERIFIED = "VERIFIED"
    FALSE_CLAIM = "FALSE_CLAIM"
    PENDING = "PENDING"


class ClaimStatus(str, Enum):
    """Lifecycle of a claim as it moves through the pipeline (distinct from `Verdict`)."""

    SUBMITTED = "submitted"
    AUDITING = "auditing"
    RESOLVED = "resolved"


class BugFinding(BaseModel):
    """One bug Replay QA found, carrying its real report URL.

    Populated from `GET /api/v1/bugs/{bug_id}` (see replay_client). `root_cause` is
    Replay's own analysis text, reported verbatim — never summarized into something
    stronger than the report says.
    """

    title: str
    severity: Optional[str] = None
    root_cause: Optional[str] = None
    url: Optional[str] = None
    bug_id: Optional[str] = None
    status: Optional[str] = None

    def to_contract(self) -> dict[str, Any]:
        """Map to the UI's `Bug` shape (ui/src/types.ts): {id?, title, severity,
        root_cause, url?}. Missing severity/root_cause are labeled, never invented into a
        stronger finding: absent severity becomes "unknown", absent root_cause an empty
        string.
        """
        return {
            "id": self.bug_id,
            "title": self.title,
            "severity": self.severity or "unknown",
            "root_cause": self.root_cause or "",
            "url": self.url,
        }


def tier_label(tier: int) -> str:
    """Render an integer tier as the UI's `Tier` string: 0 -> "L0", 1 -> "L1"."""
    return f"L{tier}"


class Claim(BaseModel):
    """A Builder (or judge) assertion that a task is complete."""

    id: str
    task_id: str
    agent_id: str
    text: str
    created_at: datetime = Field(default_factory=utcnow)
    status: ClaimStatus = ClaimStatus.SUBMITTED


class AuditResult(BaseModel):
    """The full outcome of auditing one claim against Replay QA."""

    claim_id: str
    verdict: Verdict = Verdict.PENDING
    replay_project_id: Optional[str] = None
    report_url: Optional[str] = None
    bugs: list[BugFinding] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    # Non-null only for an infra error (Replay timeout/5xx/network). Its presence is what
    # keeps the verdict PENDING and the tier unchanged — it is never a business verdict.
    error: Optional[str] = None


class TierState(BaseModel):
    """An agent's current tool-grant tier and its ratchet progress.

    * tier 0 — read-only grant (physically cannot write).
    * tier 1 — write grant (builder-l1 added to the Guild workspace).
    `streak` counts consecutive VERIFIED verdicts toward the next promotion.
    `history` is an append-only audit trail of every verdict that touched this state.
    """

    agent_id: str
    tier: int = 0
    streak: int = 0
    history: list[dict[str, Any]] = Field(default_factory=list)


# --- Event contract --------------------------------------------------------


class EventType(str, Enum):
    """Every event kind carried on the WS stream. Mirrors `ui/src/types.ts`."""

    CLAIM_SUBMITTED = "claim_submitted"
    AUDIT_STARTED = "audit_started"
    AUDIT_PROGRESS = "audit_progress"
    VERDICT_REACHED = "verdict_reached"
    TIER_CHANGED = "tier_changed"
    LIE_RECORDED = "lie_recorded"
    TRAINING_STARTED = "training_started"
    TRAINING_STATUS = "training_status"
    RECEIPTS_UPDATED = "receipts_updated"


class Event(BaseModel):
    """A single typed event on the bus.

    The discriminant is `type` (an `EventType`); `payload` carries the type-specific
    body. Every event is timestamped at construction. This shape serializes directly to
    the JSON the dashboard consumes, so the union is expressed by `type` + `payload`
    rather than a class-per-event hierarchy that would not round-trip over JSON.
    """

    type: EventType
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)

"""The tier ratchet — Replay's verdict, and only Replay's verdict, moves tool grants.

Two tiers: L0 (read-only grant) and L1 (write grant). The ratchet:
* N consecutive VERIFIED verdicts promote L0 -> L1 (capped at L1).
* ANY FALSE_CLAIM demotes to L0 and resets the streak.
* PENDING is a no-op — an infra error or in-flight audit never moves a tier.

The pure state transition (`next_tier_state`) has no IO and is exhaustively unit-tested.
`TierManager` adds durable JSON persistence (atomic writes) and the real Guild side
effect: on promotion/demotion it adds/removes the L1 agent in the Guild workspace via the
`@guildai/cli` binary. If that CLI is unavailable, the failure is recorded honestly as
`side_effect="guild_cli_unavailable"` in the event and history — local tier state still
advances, but nothing pretends the workspace changed when it did not.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from . import config
from .events import EventBus
from .models import EventType, TierState, Verdict, utcnow

# Transition labels returned by `next_tier_state`.
PROMOTED = "promoted"
DEMOTED = "demoted"


def next_tier_state(state: TierState, verdict: Verdict, ratchet_n: int) -> tuple[TierState, Optional[str]]:
    """Pure ratchet: given the current `state` and a `verdict`, return the next state and
    an optional transition label (`PROMOTED` / `DEMOTED` / None).

    Never mutates `state`; returns a new `TierState` (history carried forward, with one
    appended entry recording this verdict). PENDING returns the state unchanged with no
    history entry and no transition — it must be a true no-op.
    """
    if verdict is Verdict.PENDING:
        return state, None

    tier = state.tier
    streak = state.streak
    transition: Optional[str] = None

    if verdict is Verdict.VERIFIED:
        streak += 1
        if tier == 0 and streak >= ratchet_n:
            tier = 1
            streak = 0  # promotion consumes the streak; re-earn it to advance again
            transition = PROMOTED
    elif verdict is Verdict.FALSE_CLAIM:
        if tier == 1:
            transition = DEMOTED
        tier = 0
        streak = 0

    entry = {
        "at": utcnow().isoformat(),
        "verdict": verdict.value,
        "tier": tier,
        "streak": streak,
        "transition": transition,
    }
    new_state = TierState(
        agent_id=state.agent_id,
        tier=tier,
        streak=streak,
        history=[*state.history, entry],
    )
    return new_state, transition


class TierManager:
    """Durable, per-agent tier state plus the real Guild promotion/demotion side effect."""

    def __init__(
        self,
        state_path: Optional[Path] = None,
        bus: Optional[EventBus] = None,
        ratchet_n: Optional[int] = None,
        workspace: Optional[str] = None,
        l1_agent: Optional[str] = None,
    ) -> None:
        self._path = state_path or (config.state_dir() / "tiers.json")
        self._bus = bus
        self._ratchet_n = ratchet_n if ratchet_n is not None else config.ratchet_n()
        self._workspace = workspace or config.GUILD_WORKSPACE
        self._l1_agent = l1_agent or config.GUILD_L1_AGENT
        self._lock = asyncio.Lock()
        self._states: dict[str, TierState] = {}
        self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            self._states = {}
            return
        raw = json.loads(self._path.read_text())
        self._states = {
            agent_id: TierState.model_validate(data) for agent_id, data in raw.items()
        }

    def _save(self) -> None:
        """Atomic write: serialize to a temp file in the same dir, then os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            agent_id: state.model_dump(mode="json") for agent_id, state in self._states.items()
        }
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle, indent=2)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def get(self, agent_id: str) -> TierState:
        """Current tier state for an agent (L0 with empty history if unseen)."""
        return self._states.get(agent_id) or TierState(agent_id=agent_id)

    def all_states(self) -> dict[str, TierState]:
        return dict(self._states)

    # -- the one write path -------------------------------------------------

    async def apply_verdict(self, agent_id: str, verdict: Verdict) -> TierState:
        """Advance an agent's tier for one verdict, persist, run the Guild side effect,
        and emit a `tier_changed` event on any transition. This is the ONLY place tier
        state changes — Guild promote/demote must never be called from anywhere else.
        """
        async with self._lock:
            current = self.get(agent_id)
            new_state, transition = next_tier_state(current, verdict, self._ratchet_n)

            side_effect: Optional[str] = None
            if transition is not None:
                side_effect = await self._run_guild_side_effect(transition)
                # Record the real side-effect outcome on the just-appended history entry.
                if new_state.history:
                    new_state.history[-1]["side_effect"] = side_effect

            self._states[agent_id] = new_state
            self._save()

            if transition is not None and self._bus is not None:
                await self._bus.emit(
                    EventType.TIER_CHANGED,
                    agent_id=agent_id,
                    transition=transition,
                    tier=new_state.tier,
                    streak=new_state.streak,
                    side_effect=side_effect,
                    verdict=verdict.value,
                )
            return new_state

    async def _run_guild_side_effect(self, transition: str) -> str:
        """Add (promote) or remove (demote) the L1 agent in the Guild workspace.

        Runs `npx --yes @guildai/cli@latest workspace agent <add|remove> <l1_agent>
        --workspace <workspace>` in a thread (subprocess is blocking). Returns a short
        status string recorded in the event/history:
          * "guild_agent_added" / "guild_agent_removed" on success,
          * "guild_cli_error" if the CLI ran but returned non-zero,
          * "guild_cli_unavailable" if the CLI could not be executed at all.
        Local tier state advances regardless — the status is the honest record of whether
        the workspace actually changed.
        """
        action = "add" if transition == PROMOTED else "remove"
        cmd = [
            "npx", "--yes", "@guildai/cli@latest",
            "workspace", "agent", action, self._l1_agent,
            "--workspace", self._workspace,
        ]

        def _run() -> tuple[int, str]:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            return proc.returncode, (proc.stderr or proc.stdout or "").strip()

        try:
            returncode, output = await asyncio.to_thread(_run)
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return "guild_cli_unavailable"
        if returncode == 0:
            return "guild_agent_added" if action == "add" else "guild_agent_removed"
        return "guild_cli_error"

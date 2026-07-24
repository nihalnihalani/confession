"""Runtime configuration read from the process environment.

Every value here comes from a real environment variable (see the repo `.env.example`).
There are no baked-in credentials and no silent defaults for secrets: when a secret is
missing the dependent client raises a typed, actionable error rather than pretending to
work.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _engine_dir() -> Path:
    """Absolute path to the `engine/` directory that contains this package."""
    return Path(__file__).resolve().parent.parent


def state_dir() -> Path:
    """Directory where durable state (tiers, caught lies, training log) is persisted.

    Defaults to `engine/state/`. Override with CONFESSION_STATE_DIR (useful for tests).
    The directory is created on first use by the callers that write into it.
    """
    override = os.getenv("CONFESSION_STATE_DIR")
    return Path(override).resolve() if override else _engine_dir() / "state"


# --- Replay QA -------------------------------------------------------------

# The Replay QA OpenAPI spec (sponsor-docs/replay/loop-qa-openapi.json) declares
# servers[0].url = "https://qa.replay.io" and prefixes every path with "/api/v1".
# The repo notes also reference "https://loop-qa.replay.io/api/v1"; the host is one of
# the two items CLAUDE.md flags for on-site verification. Both the host and the path
# prefix are therefore overridable from the environment without a code change.
REPLAY_BASE_URL = os.getenv("REPLAY_BASE_URL", "https://qa.replay.io").rstrip("/")
REPLAY_API_PREFIX = os.getenv("REPLAY_API_PREFIX", "/api/v1")
REPLAY_API_TOKEN = os.getenv("REPLAY_API_TOKEN")

TARGET_APP_URL = os.getenv("TARGET_APP_URL")

# --- Pioneer ---------------------------------------------------------------

PIONEER_BASE_URL = os.getenv("PIONEER_BASE_URL", "https://api.pioneer.ai").rstrip("/")
PIONEER_API_KEY = os.getenv("PIONEER_API_KEY")
PIONEER_MODEL = os.getenv("PIONEER_MODEL")

# --- Guild -----------------------------------------------------------------

# Guild auth lives in the `guild auth login` CLI state; there is no env token.
GUILD_WORKSPACE = os.getenv("GUILD_WORKSPACE", "confession/confession")
# The Guild agent whose write-tool grant is added on promotion and removed on demotion.
GUILD_L1_AGENT = os.getenv("GUILD_L1_AGENT", "builder-l1")

# --- Builder loop ----------------------------------------------------------

# The Guild agent the Builder loop invokes at tier L0 (read-only grant). The L1 agent
# (write grant) is either GUILD_BUILDER_L1_AGENT or, if unset, derived by swapping the
# "l0" marker for "l1" — so a promoted builder literally runs as the write-grant agent.
GUILD_BUILDER_AGENT = os.getenv("GUILD_BUILDER_AGENT", "confession~confession-builder-l0")
GUILD_BUILDER_L1_AGENT = os.getenv("GUILD_BUILDER_L1_AGENT")

# The stable logical identity the Builder claims under and whose tier is ratcheted. It is
# deliberately independent of the tier-specific Guild agent name above (the same logical
# builder is what gets promoted L0 -> L1).
BUILDER_AGENT_ID = os.getenv("CONFESSION_BUILDER_AGENT_ID", "builder")


def tasks_file() -> Path:
    """Path to the real target-app task list the Builder picks work from.

    Defaults to `target-app/TASKS.md` under the repository root. A relative TASKS_FILE
    override is also resolved from the repository root so CLI/server working-directory
    differences cannot silently point the Builder at the wrong file.
    """
    override = os.getenv("TASKS_FILE")
    if not override:
        return _engine_dir().parent / "target-app" / "TASKS.md"
    path = Path(override).expanduser()
    return path.resolve() if path.is_absolute() else (_engine_dir().parent / path).resolve()


def guild_builder_agent(tier: int) -> str:
    """The Guild agent to invoke for a given builder tier: L0 uses GUILD_BUILDER_AGENT;
    L1 uses GUILD_BUILDER_L1_AGENT, or the L0 name with its "l0" marker swapped to "l1"."""
    if tier >= 1:
        if GUILD_BUILDER_L1_AGENT:
            return GUILD_BUILDER_L1_AGENT
        return _swap_tier_marker(GUILD_BUILDER_AGENT)
    return GUILD_BUILDER_AGENT


def _swap_tier_marker(agent: str) -> str:
    for lo, hi in (("l0", "l1"), ("L0", "L1")):
        if lo in agent:
            return agent.replace(lo, hi)
    return agent


# --- Agent identity policy -------------------------------------------------


def allowed_agents() -> Optional[set[str]]:
    """The set of agent_ids permitted to submit claims over HTTP, or None when no
    allowlist is configured (any agent_id accepted). Set CONFESSION_ALLOWED_AGENTS to a
    comma-separated list to enable it; judge identities are always allowed regardless."""
    raw = os.getenv("CONFESSION_ALLOWED_AGENTS")
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def judge_agents() -> set[str]:
    """Identities whose claims run the full audit but never move any tier and never feed
    the fine-tune ledger — a judge's test claim is not genuine builder behavior. Defaults
    to {"judge"}; override with CONFESSION_JUDGE_AGENTS (comma-separated)."""
    raw = os.getenv("CONFESSION_JUDGE_AGENTS", "judge")
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_judge_agent(agent_id: str) -> bool:
    return agent_id in judge_agents()


# --- Re-audit loop ---------------------------------------------------------


def reaudit_interval_s() -> float:
    try:
        return max(1.0, float(os.getenv("REAUDIT_INTERVAL_S", "120")))
    except ValueError:
        return 120.0


def reaudit_max_attempts() -> int:
    try:
        return max(0, int(os.getenv("REAUDIT_MAX_ATTEMPTS", "3")))
    except ValueError:
        return 3


# --- CORS ------------------------------------------------------------------


def cors_origins() -> list[str]:
    """Allowed browser origins for the dashboard. Defaults to the local Vite dev pair;
    override with CORS_ORIGINS (comma-separated) for a deployed dashboard."""
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- Tier ratchet ----------------------------------------------------------


def ratchet_n() -> int:
    """Number of consecutive VERIFIED verdicts required to promote L0 -> L1."""
    try:
        return max(1, int(os.getenv("CONFESSION_RATCHET_N", "3")))
    except ValueError:
        return 3


def replay_configured() -> bool:
    return bool(REPLAY_API_TOKEN)


def pioneer_configured() -> bool:
    return bool(PIONEER_API_KEY)

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
from urllib.parse import urlparse

from dotenv import load_dotenv


def _engine_dir() -> Path:
    """Absolute path to the `engine/` directory that contains this package."""
    return Path(__file__).resolve().parent.parent


load_dotenv(_engine_dir().parent / ".env", override=False)


def state_dir() -> Path:
    """Directory where durable state (tiers, caught lies, training log) is persisted.

    Defaults to `engine/state/`. Override with CONFESSION_STATE_DIR (useful for tests).
    The directory is created on first use by the callers that write into it.
    """
    override = os.getenv("CONFESSION_STATE_DIR")
    return Path(override).resolve() if override else _engine_dir() / "state"


def database_path() -> Path:
    """Durable SQLite database for claims, results, events, jobs, and request keys."""
    override = os.getenv("CONFESSION_DATABASE_PATH")
    if not override:
        return state_dir() / "confession.sqlite3"
    path = Path(override).expanduser()
    return path.resolve() if path.is_absolute() else (_engine_dir().parent / path).resolve()


def serve_ui() -> bool:
    """Whether this process serves the built dashboard on the same origin."""
    return os.getenv("CONFESSION_SERVE_UI", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def ui_dist_path() -> Path:
    """Built Vite dashboard directory used by the single-container deployment."""
    override = os.getenv("CONFESSION_UI_DIST")
    if not override:
        return _engine_dir().parent / "ui" / "dist"
    path = Path(override).expanduser()
    return path.resolve() if path.is_absolute() else (_engine_dir().parent / path).resolve()


# --- Runtime/security ------------------------------------------------------

ENVIRONMENT = os.getenv("CONFESSION_ENV", "development").strip().lower()


def auth_required() -> bool:
    """Mutation APIs are secure-by-default in production and opt-in during local work."""
    raw = os.getenv("CONFESSION_AUTH_REQUIRED")
    if raw is None:
        return ENVIRONMENT == "production"
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def api_keys() -> dict[str, set[str]]:
    """Parse `role:key` entries from CONFESSION_API_KEYS.

    Supported roles are `judge`, `builder`, and `operator`. An operator may call every
    mutation endpoint; the other roles are limited to their own workflow.
    """
    entries: dict[str, set[str]] = {}
    raw = os.getenv("CONFESSION_API_KEYS", "")
    for item in raw.split(","):
        role, separator, token = item.strip().partition(":")
        if not separator or not role or not token:
            continue
        entries.setdefault(role.strip().lower(), set()).add(token.strip())
    return entries


def rate_limit_per_minute() -> int:
    try:
        return max(1, int(os.getenv("CONFESSION_RATE_LIMIT_PER_MINUTE", "30")))
    except ValueError:
        return 30


def builder_requires_deployed_target() -> bool:
    raw = os.getenv("BUILDER_REQUIRE_DEPLOYED_TARGET")
    if raw is None:
        return ENVIRONMENT == "production"
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def target_app_allowed_hosts() -> set[str]:
    """Hosts a Builder claim may ask Replay to inspect."""
    hosts = {
        item.strip().lower()
        for item in os.getenv("TARGET_APP_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    if TARGET_APP_URL:
        host = urlparse(TARGET_APP_URL).hostname
        if host:
            hosts.add(host.lower())
    return hosts


def guild_reconcile_interval_s() -> float:
    try:
        return max(5.0, float(os.getenv("GUILD_RECONCILE_INTERVAL_S", "60")))
    except ValueError:
        return 60.0


def guild_reconcile_max_attempts() -> int:
    try:
        return max(1, int(os.getenv("GUILD_RECONCILE_MAX_ATTEMPTS", "3")))
    except ValueError:
        return 3


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


def target_app_configured() -> bool:
    """Whether the configured target is a valid Replay acceptance surface."""
    if not TARGET_APP_URL:
        return False
    parsed = urlparse(TARGET_APP_URL)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        return False
    return ENVIRONMENT != "production" or parsed.scheme == "https"

# --- Pioneer ---------------------------------------------------------------

PIONEER_BASE_URL = os.getenv("PIONEER_BASE_URL", "https://api.pioneer.ai").rstrip("/")
PIONEER_API_KEY = os.getenv("PIONEER_API_KEY")
PIONEER_MODEL = os.getenv("PIONEER_MODEL")

# --- Guild -----------------------------------------------------------------

# Guild auth lives in the `guild auth login` CLI state; there is no env token.
GUILD_WORKSPACE = os.getenv("GUILD_WORKSPACE", "confession/confession")
GUILD_CLI_PACKAGE = os.getenv("GUILD_CLI_PACKAGE", "@guildai/cli@0.12.3")

# --- Builder loop ----------------------------------------------------------

# The Guild agent the Builder loop invokes at tier L0 (read-only grant). The L1 agent
# (write grant) is either GUILD_BUILDER_L1_AGENT or, if unset, derived by swapping the
# "l0" marker for "l1" — so a promoted builder literally runs as the write-grant agent.
GUILD_BUILDER_AGENT = os.getenv("GUILD_BUILDER_AGENT", "confession~confession-builder-l0")
GUILD_BUILDER_L1_AGENT = os.getenv(
    "GUILD_BUILDER_L1_AGENT", "confession~confession-builder-l1"
)
# The exact same L1 agent is added/removed from the workspace and invoked after a
# confirmed transition. A separate override remains for unusual Guild installations.
GUILD_L1_AGENT = os.getenv("GUILD_L1_AGENT", GUILD_BUILDER_L1_AGENT)

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


# --- Pioneer automation ----------------------------------------------------


def pioneer_autotrain_min_lies() -> int:
    """Caught-lie threshold for automatic training; zero disables automatic training."""
    try:
        return max(0, int(os.getenv("PIONEER_AUTOTRAIN_MIN_LIES", "0")))
    except ValueError:
        return 0


PIONEER_BASE_MODEL = os.getenv("PIONEER_BASE_MODEL")


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

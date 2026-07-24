"""Runtime configuration read from the process environment.

Every value here comes from a real environment variable (see the repo `.env.example`).
There are no baked-in credentials and no silent defaults for secrets: when a secret is
missing the dependent client raises a typed, actionable error rather than pretending to
work.
"""

from __future__ import annotations

import os
from pathlib import Path


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

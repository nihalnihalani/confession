"""Authentication, authorization, idempotency-key validation, and request limiting."""

from __future__ import annotations

import secrets
from typing import Iterable, Optional

from fastapi import HTTPException, Request

from . import config
from .state import StateStore


def authorize(request: Request, roles: Iterable[str]) -> str:
    """Return the authenticated role or reject the request.

    Development may explicitly run without credentials. Production defaults to requiring
    a bearer key from CONFESSION_API_KEYS. Operator keys are allowed on every mutation.
    """
    allowed = {role.lower() for role in roles}
    if not config.auth_required():
        return "development"

    configured = config.api_keys()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Mutation access is enabled but CONFESSION_API_KEYS is not configured.",
        )

    token = _request_token(request)
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="A Bearer access key is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    for role, keys in configured.items():
        if role != "operator" and role not in allowed:
            continue
        if any(secrets.compare_digest(token, key) for key in keys):
            return role
    raise HTTPException(status_code=403, detail="This access key cannot perform that action.")


def enforce_identity(role: str, agent_id: str) -> None:
    """Bind authenticated roles to the identities they are permitted to submit as."""
    if role in {"development", "operator"}:
        return
    if role == "judge" and config.is_judge_agent(agent_id):
        return
    if role == "builder" and agent_id == config.BUILDER_AGENT_ID:
        return
    raise HTTPException(
        status_code=403,
        detail=f"Role {role!r} cannot submit as agent_id {agent_id!r}.",
    )


def enforce_rate_limit(
    request: Request,
    store: StateStore,
    scope: str,
    role: str,
    multiplier: int = 1,
) -> None:
    client = request.client.host if request.client is not None else "unknown"
    bucket = f"{scope}:{role}:{client}"
    limit = config.rate_limit_per_minute() * max(1, multiplier)
    if not store.consume_rate(bucket, limit):
        raise HTTPException(
            status_code=429,
            detail="Request limit reached. Retry in one minute.",
            headers={"Retry-After": "60"},
        )


def idempotency_key(request: Request, required: bool = True) -> Optional[str]:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value:
        if required:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key header is required for mutation requests.",
            )
        return None
    if len(value) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise HTTPException(status_code=400, detail="Idempotency-Key is invalid.")
    return value


def _request_token(request: Request) -> Optional[str]:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and token.strip():
        return token.strip()
    alternate = request.headers.get("X-Confession-Key", "").strip()
    return alternate or None

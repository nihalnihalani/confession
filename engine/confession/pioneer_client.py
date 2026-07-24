"""Pioneer client — inference and the caught-lie fine-tune loop.

Auth is `X-API-Key` (NOT Bearer). Base URL defaults to https://api.pioneer.ai and is
overridable via PIONEER_BASE_URL.

Endpoint shapes:
* `chat` / `list_models` follow the OpenAI-compatible surface documented in
  sponsor-docs/pioneer/llms.txt (`/v1/chat/completions`, `/v1/models`).
* The fine-tune surface (`/generate`, `/felix/training-jobs`, registry) follows the flow
  captured in the repo CLAUDE.md sponsor notes. Those paths are marked below and should
  be confirmed against docs.pioneer.ai/openapi.json before the live fine-tune run.

Missing key raises `PioneerNotConfigured` with an actionable message — never a silent
fallback and never automatic firing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from . import config

DEFAULT_HTTP_TIMEOUT_S = 60.0
DEFAULT_POLL_INTERVAL_S = 15.0
DEFAULT_POLL_TIMEOUT_S = 3600.0


class PioneerError(Exception):
    """Base class for Pioneer client errors."""


class PioneerNotConfigured(PioneerError):
    """PIONEER_API_KEY is not set — no Pioneer call may proceed."""


class PioneerInfraError(PioneerError):
    """A transport/HTTP failure talking to Pioneer."""


class PioneerModelUnavailable(PioneerError):
    """The configured PIONEER_MODEL is not present in `GET /v1/models`."""


class PioneerClient:
    """Async client for the Pioneer REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        http_timeout_s: float = DEFAULT_HTTP_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key if api_key is not None else config.PIONEER_API_KEY
        if not self._api_key:
            raise PioneerNotConfigured(
                "PIONEER_API_KEY is not set. Generate a key at pioneer.ai and export "
                "PIONEER_API_KEY=pio_sk_... (auth header is X-API-Key, not Bearer). "
                "Nothing in the fine-tune flow runs until this is configured."
            )
        self._base_url = (base_url or config.PIONEER_BASE_URL).rstrip("/")
        self._http_timeout = http_timeout_s

    # -- low-level ----------------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        # Pioneer authenticates with X-API-Key, NOT Authorization: Bearer.
        return {"X-API-Key": self._api_key, "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.request(method, url, headers=self._headers, **kwargs)
                response.raise_for_status()
                if response.content:
                    return response.json()
                return None
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response is not None else ""
            raise PioneerInfraError(
                f"Pioneer {method} {path} returned {exc.response.status_code}: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise PioneerInfraError(f"Pioneer {method} {path} transport error: {exc}") from exc

    # -- inference ----------------------------------------------------------

    async def chat(self, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """OpenAI-compatible chat completion.

        `POST /v1/chat/completions` with body `{model, messages}` only (per the repo
        sponsor notes — no extra fields).
        """
        return await self._request(
            "POST", "/v1/chat/completions", json={"model": model, "messages": messages}
        )

    async def list_models(self) -> list[str]:
        """List available model ids. `GET /v1/models` (OpenAI-compatible listing)."""
        result = await self._request("GET", "/v1/models")
        return _model_ids(result)

    async def validate_model(self, model: str) -> None:
        """Confirm `model` appears in `GET /v1/models`; hard-fail if not.

        A past winner hit a 404 on an unlisted default model, so this is called at
        startup before any inference is routed to `model`.
        """
        available = await self.list_models()
        if model not in available:
            raise PioneerModelUnavailable(
                f"PIONEER_MODEL={model!r} is not in GET /v1/models. Available: {available}. "
                "Set PIONEER_MODEL to a listed id (after fine-tune, the training-job id)."
            )

    # -- fine-tune flow (paths per CLAUDE.md sponsor notes; verify on-site) --

    async def generate_dataset(self, name: str, examples: list[dict[str, Any]]) -> dict[str, Any]:
        """Start a data-generation job that builds a training dataset from examples.

        `POST /generate`. Returns the job/dataset descriptor (poll via
        `poll_generate_job`).
        """
        return await self._request("POST", "/generate", json={"name": name, "examples": examples})

    async def get_generate_job(self, job_id: str) -> dict[str, Any]:
        """`GET /generate/jobs/{job_id}` — status of a data-generation job."""
        return await self._request("GET", f"/generate/jobs/{job_id}")

    async def start_finetune(
        self,
        dataset_name: str,
        version: str,
        base_model: str,
        model_name: Optional[str] = None,
        nr_epochs: int = 3,
        learning_rate: float = 2e-5,
    ) -> dict[str, Any]:
        """Start a LoRA fine-tune job.

        `POST /felix/training-jobs` with body
        `{model_name, base_model, training_type:"lora", datasets, nr_epochs, learning_rate}`.
        The returned training-job id is directly usable as the chat model id (set it as
        PIONEER_MODEL and the live agents run on it).
        """
        body: dict[str, Any] = {
            "model_name": model_name or f"confession-{dataset_name}-{version}",
            "base_model": base_model,
            "training_type": "lora",
            "datasets": [{"name": dataset_name, "version": version}],
            "nr_epochs": nr_epochs,
            "learning_rate": learning_rate,
        }
        return await self._request("POST", "/felix/training-jobs", json=body)

    async def get_finetune_job(self, job_id: str) -> dict[str, Any]:
        """`GET /felix/training-jobs/{job_id}` — status of a fine-tune job."""
        return await self._request("GET", f"/felix/training-jobs/{job_id}")

    async def list_registry(self) -> Any:
        """List the model registry (trained checkpoints). `GET /felix/models`."""
        return await self._request("GET", "/felix/models")

    async def poll_job(
        self,
        fetch: Any,
        job_id: str,
        on_status: Optional[Any] = None,
        interval_s: float = DEFAULT_POLL_INTERVAL_S,
        timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Generic poller: repeatedly call `fetch(job_id)` until it reports terminal.

        `fetch` is one of `get_generate_job` / `get_finetune_job`. The optional async
        `on_status(status)` callback is invoked on every poll (used to append each real
        response to the training log). Terminal statuses: succeeded/completed/failed/
        cancelled/error. Raises `PioneerInfraError` on timeout.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_s
        terminal = {"succeeded", "completed", "complete", "failed", "cancelled", "canceled", "error"}
        while True:
            status = await fetch(job_id)
            if on_status is not None:
                await on_status(status)
            state = str(_job_state(status)).lower()
            if state in terminal:
                return status
            if loop.time() >= deadline:
                raise PioneerInfraError(
                    f"Pioneer job {job_id} did not reach a terminal state within {timeout_s:.0f}s"
                )
            await asyncio.sleep(interval_s)


# --- response helpers ------------------------------------------------------


def _model_ids(result: Any) -> list[str]:
    """Extract model ids from a `GET /v1/models` response (OpenAI-compatible shape)."""
    items: list[Any]
    if isinstance(result, dict):
        raw = result.get("data") or result.get("models") or []
        items = raw if isinstance(raw, list) else []
    elif isinstance(result, list):
        items = result
    else:
        items = []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
            if model_id is not None:
                ids.append(str(model_id))
        elif isinstance(item, str):
            ids.append(item)
    return ids


SUCCESS_STATES = frozenset({"succeeded", "completed", "complete"})


def job_state_of(status: Any) -> str:
    """Extract a job's state string from a status payload, defensively (lowercased)."""
    if isinstance(status, dict):
        raw = status.get("status") or status.get("state") or status.get("phase") or "unknown"
        return str(raw).lower()
    return "unknown"


def is_success_state(state: str) -> bool:
    """True when a job state string denotes successful completion."""
    return state.lower() in SUCCESS_STATES


def _job_state(status: Any) -> str:
    return job_state_of(status)


def job_id_of(response: Any) -> Optional[str]:
    """Best-effort extraction of a job id from a Pioneer job-creation response."""
    if isinstance(response, dict):
        for key in ("id", "job_id", "training_job_id", "jobId"):
            value = response.get(key)
            if value:
                return str(value)
    return None

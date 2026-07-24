"""Replay QA REST client — the verdict oracle.

Implemented against the Replay QA OpenAPI spec committed at `docs/replay-openapi.json`
(the live copy is served from the API host under `/api/v1/openapi.json`). Endpoint paths
and request/response fields below are cited from that spec by operationId.

The spec's "Continuous QA workflow" is explicit that Replay drives exploration and
testing itself: after `POST /api/v1/projects` you poll status and read bugs — you do NOT
start your own explorations or test runs. This client follows that: `create_project`
kicks off QA, `poll_until_finished` waits on the project timing/status, and `fetch_bugs`
returns the real findings with their report URLs. `start_exploration` exists for spec
completeness but is deliberately not part of the audit path.

Any HTTP or network failure raises `ReplayInfraError`. The client never fabricates a
result on error — an infra error must surface as PENDING upstream, never as a verdict.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from . import config
from .models import BugFinding


class ReplayError(Exception):
    """Base class for Replay client errors."""


class ReplayConfigError(ReplayError):
    """No REPLAY_API_TOKEN configured — the client cannot authenticate."""


class ReplayInfraError(ReplayError):
    """A transport/HTTP/timeout failure talking to Replay.

    Upstream treats this as PENDING (never a pass, never a lie): the claim is re-audited
    later. Poll timeouts are also raised as this type, per CLAUDE.md's rule that a Replay
    timeout is an infra condition, not a verdict.
    """


# Default polling cadence. Real exploration round-trip latency is flagged for on-site
# verification (CLAUDE.md VERIFY ON-SITE #1); interval/timeout are caller-overridable.
DEFAULT_POLL_INTERVAL_S = 10.0
DEFAULT_POLL_TIMEOUT_S = 900.0
DEFAULT_HTTP_TIMEOUT_S = 30.0


class ReplayClient:
    """Async client for the Replay QA REST API."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        api_prefix: Optional[str] = None,
        http_timeout_s: float = DEFAULT_HTTP_TIMEOUT_S,
    ) -> None:
        self._token = api_token if api_token is not None else config.REPLAY_API_TOKEN
        if not self._token:
            raise ReplayConfigError(
                "REPLAY_API_TOKEN is not set. Generate a token in Replay QA Settings "
                "(after applying promo code HACKATHON) and export REPLAY_API_TOKEN=lqa_..."
            )
        self._base_url = (base_url or config.REPLAY_BASE_URL).rstrip("/")
        self._prefix = api_prefix if api_prefix is not None else config.REPLAY_API_PREFIX
        self._http_timeout = http_timeout_s

    # -- low-level ----------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base_url}{self._prefix}{path}"

    @property
    def _headers(self) -> dict[str, str]:
        # Spec: Authorization: Bearer lqa_...  (bearerAuth security scheme).
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Perform one HTTP call, raising ReplayInfraError on any transport/HTTP failure."""
        url = self._url(path)
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.request(method, url, headers=self._headers, **kwargs)
                response.raise_for_status()
                if response.content:
                    return response.json()
                return None
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response is not None else ""
            raise ReplayInfraError(
                f"Replay {method} {path} returned {exc.response.status_code}: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ReplayInfraError(f"Replay {method} {path} transport error: {exc}") from exc

    # -- projects -----------------------------------------------------------

    async def create_project(
        self,
        target_url: str,
        name: str,
        instructions: Optional[str] = None,
        design_document: Optional[str] = None,
        logins: Optional[list[dict[str, str]]] = None,
        budget: Optional[float] = None,
        use_reverse_proxy: bool = False,
        webhook_url: Optional[str] = None,
        finished_webhook_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a QA project and start automated exploration.

        Spec: `POST /api/v1/projects` (operationId createProject). Required body fields
        are `name` and `target_url`. The response is documented to include an
        `exploration_id` and a `url` (link to the project dashboard). This method returns
        the raw response dict; use `project_id_of` / `dashboard_url_of` to extract fields
        defensively (the spec documents the response prose but not a strict schema).
        """
        body: dict[str, Any] = {"name": name, "target_url": target_url}
        if instructions is not None:
            body["instructions"] = instructions
        if design_document is not None:
            body["design_document"] = design_document
        if logins is not None:
            body["logins"] = logins
        if budget is not None:
            body["budget"] = budget
        if use_reverse_proxy:
            body["use_reverse_proxy"] = True
        if webhook_url is not None:
            body["webhook_url"] = webhook_url
        if finished_webhook_url is not None:
            body["finished_webhook_url"] = finished_webhook_url
        result = await self._request("POST", "/projects", json=body)
        if not isinstance(result, dict):
            raise ReplayInfraError(f"createProject returned unexpected body: {result!r}")
        return result

    async def get_project(self, project_id: str) -> dict[str, Any]:
        """Spec: `GET /api/v1/projects/{project_id}` (operationId getProject)."""
        return await self._request("GET", f"/projects/{project_id}")

    async def get_status(self, project_id: str) -> dict[str, Any]:
        """Project summary with counts of explorations, journeys, test runs, and bugs.

        Spec: `GET /api/v1/projects/{project_id}/status` (operationId getProjectStatus).
        """
        return await self._request("GET", f"/projects/{project_id}/status")

    async def get_timing(self, project_id: str) -> dict[str, Any]:
        """Project timing milestones on a single server clock.

        Spec: `GET /api/v1/projects/{project_id}/timing` (operationId getProjectTiming).
        `finished_at` is null while QA is still running and set once the project goes
        idle — this is the authoritative completion signal used by `poll_until_finished`.
        """
        return await self._request("GET", f"/projects/{project_id}/timing")

    async def start_exploration(self, project_id: str, prompt: Optional[str] = None) -> dict[str, Any]:
        """Manually start an AI exploration.

        Spec: `POST /api/v1/projects/{project_id}/explorations` (operationId
        startExploration). Provided for spec completeness only — the documented
        Continuous QA workflow says QA drives exploration itself and callers should NOT
        start their own. The audit pipeline does not call this.
        """
        body = {"prompt": prompt} if prompt is not None else {}
        return await self._request("POST", f"/projects/{project_id}/explorations", json=body)

    # -- polling ------------------------------------------------------------

    async def poll_until_finished(
        self,
        project_id: str,
        interval_s: float = DEFAULT_POLL_INTERVAL_S,
        timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
        on_progress: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Poll the project until QA goes idle, returning the final status summary.

        Completion is detected via `get_timing().finished_at` becoming non-null (spec:
        "when the project last went idle; null while QA is still running"). Between polls
        the current status summary is passed to the optional async `on_progress(status)`
        callback so the auditor can emit progress events.

        Raises `ReplayInfraError` if `timeout_s` elapses before QA finishes — a timeout is
        an infra condition (PENDING + re-audit), not a verdict.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_s
        while True:
            timing = await self.get_timing(project_id)
            status = await self.get_status(project_id)
            if on_progress is not None:
                await on_progress(status)
            if timing.get("finished_at") is not None:
                return status
            if loop.time() >= deadline:
                raise ReplayInfraError(
                    f"Replay project {project_id} did not finish within {timeout_s:.0f}s "
                    f"(last status: {status})"
                )
            await asyncio.sleep(interval_s)

    # -- bugs ---------------------------------------------------------------

    async def list_bug_ids(self, project_id: str, status: str = "open") -> list[str]:
        """List bug ids for a project filtered by status.

        Spec: `GET /api/v1/projects/{project_id}/bugs?status=open` (operationId listBugs).
        The response shape is documented in prose ("List of bugs"); ids are extracted
        defensively from common container/field names.
        """
        result = await self._request(
            "GET", f"/projects/{project_id}/bugs", params={"status": status, "page_size": 100}
        )
        items = _as_item_list(result)
        ids: list[str] = []
        for item in items:
            if isinstance(item, dict):
                bug_id = item.get("id") or item.get("bug_id")
                if bug_id is not None:
                    ids.append(str(bug_id))
            elif isinstance(item, str):
                ids.append(item)
        return ids

    async def get_bug(self, bug_id: str) -> dict[str, Any]:
        """Full bug investigation incl. root-cause analysis and reproduction steps.

        Spec: `GET /api/v1/bugs/{bug_id}` (operationId getBug). Includes reproduction
        steps, expected vs. actual behavior, a screenshot chronology, and a root-cause
        analysis traced through the Replay recording (app.replay.io/recording/<id>).
        """
        return await self._request("GET", f"/bugs/{bug_id}")

    async def fetch_bugs(self, project_id: str, status: str = "open") -> list[BugFinding]:
        """Return the project's bugs as `BugFinding`s, each with its real report URL.

        Lists bug ids then fetches each bug's full detail, mapping Replay's own fields to
        `BugFinding`. `root_cause` is Replay's analysis text, reported verbatim.
        """
        bug_ids = await self.list_bug_ids(project_id, status=status)
        findings: list[BugFinding] = []
        for bug_id in bug_ids:
            detail = await self.get_bug(bug_id)
            findings.append(_bug_finding_from_detail(bug_id, detail))
        return findings


# --- response helpers ------------------------------------------------------


def project_id_of(create_response: dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of the project id from a createProject response."""
    for key in ("project_id", "id", "projectId"):
        value = create_response.get(key)
        if value:
            return str(value)
    project = create_response.get("project")
    if isinstance(project, dict):
        return project_id_of(project)
    return None


def dashboard_url_of(create_response: dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of the project dashboard `url` from a createProject response."""
    for key in ("url", "dashboard_url", "project_url"):
        value = create_response.get(key)
        if value:
            return str(value)
    return None


def _as_item_list(result: Any) -> list[Any]:
    """Normalize a list-style Replay response into a plain list of items."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("bugs", "items", "data", "results"):
            value = result.get(key)
            if isinstance(value, list):
                return value
    return []


def _recording_url(detail: dict[str, Any]) -> Optional[str]:
    """Build the app.replay.io recording URL from a bug detail, when present."""
    recording_id = detail.get("replay_recording_id") or detail.get("recording_id")
    if recording_id:
        return f"https://app.replay.io/recording/{recording_id}"
    return None


def _bug_finding_from_detail(bug_id: str, detail: dict[str, Any]) -> BugFinding:
    """Map a Replay bug detail payload onto our `BugFinding` model, defensively."""
    root_cause = (
        detail.get("analysis")
        or detail.get("root_cause")
        or detail.get("actual_behavior")
    )
    url = (
        detail.get("url")
        or detail.get("report_url")
        or _recording_url(detail)
    )
    return BugFinding(
        bug_id=bug_id,
        title=str(detail.get("title") or f"bug {bug_id}"),
        severity=_opt_str(detail.get("severity")),
        root_cause=_opt_str(root_cause),
        url=_opt_str(url),
        status=_opt_str(detail.get("status")),
    )


def _opt_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)

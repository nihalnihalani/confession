"""The autonomous Builder loop — real agent work turned into real audited claims.

This closes the Autonomy loop: instead of a human typing a claim string, the Builder
loop (a) picks a real task from the target app's TASKS.md, (b) invokes the REAL Guild
builder agent to attempt it, (c) parses the agent's own `[CLAIM ...]` block out of its
real output, and (d) submits that claim into the SAME audit pipeline every other claim
goes through. Nothing here fabricates agent output: if the Guild CLI is unavailable or
unauthenticated, it raises `BuilderNotConfigured` and stops (realness law).

The Builder is deliberately blind to the Auditor/Replay pipeline — the prompt it receives
never mentions QA, verdicts, or tiers. The referee's independence is the product.

The Guild agent invoked tracks the builder's current tier: at L0 it runs the read-only
agent; once promoted to L1 it runs the write-grant agent — so promotion is a real change
in the tools the builder actually holds.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel

from . import config
from .auditor import Auditor
from .events import EventBus
from .models import AuditResult, Claim, EventType, utcnow
from .tiers import TierManager

ResultSink = Callable[[Claim, AuditResult], Awaitable[None]]

DEFAULT_BUILDER_TIMEOUT_S = float(os.getenv("BUILDER_TIMEOUT_S", "600"))


class BuilderError(Exception):
    """Base class for Builder loop errors."""


class BuilderNotConfigured(BuilderError):
    """The Guild CLI could not be run (not installed, not on PATH, or unauthenticated).

    Raised instead of ever fabricating agent output — no real agent run, no claim.
    """


class BuilderTask(BaseModel):
    """One task parsed from the target app's TASKS.md."""

    id: str
    title: str
    details: str = ""
    done: bool = False


class ParsedClaim(BaseModel):
    """A `[CLAIM ...]` block extracted from the Builder agent's real output."""

    task_id: str
    status: Literal["done", "blocked"]
    summary: str = ""
    target_url: Optional[str] = None
    evidence_url: Optional[str] = None


# Tolerant matcher for a claim block anywhere in the agent's prose. `body` is captured up
# to the first closing bracket; DOTALL lets a summary span multiple lines.
_CLAIM_BLOCK_RE = re.compile(r"\[\s*CLAIM\b(?P<body>[^\]]*)\]", re.IGNORECASE | re.DOTALL)
_TASK_RE = re.compile(r"task\s*=\s*(?P<task>[^\s\]]+)", re.IGNORECASE)
_STATUS_RE = re.compile(r"status\s*=\s*(?P<status>done|blocked)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"summary\s*=\s*(?P<summary>.*)", re.IGNORECASE | re.DOTALL)
_TARGET_RE = re.compile(r"target_url\s*=\s*(?P<url>https?://[^\s\]]+)", re.IGNORECASE)
_EVIDENCE_RE = re.compile(
    r"(?:evidence_url|pr)\s*=\s*(?P<url>https?://[^\s\]]+)",
    re.IGNORECASE,
)


def parse_claim_block(text: str) -> Optional[ParsedClaim]:
    """Extract a `[CLAIM task=<id> status=done|blocked summary=...]` block from `text`.

    Tolerant of surrounding prose and of field spacing; the summary may span lines. If
    there is no claim block, or a block is present but missing a valid task/status, this
    returns None — the caller then records the run honestly and runs no audit. A
    malformed block is never guessed into a claim.
    """
    if not text:
        return None
    match = _CLAIM_BLOCK_RE.search(text)
    if not match:
        return None
    body = match.group("body")
    task_match = _TASK_RE.search(body)
    status_match = _STATUS_RE.search(body)
    if not task_match or not status_match:
        return None
    summary = ""
    summary_match = _SUMMARY_RE.search(body)
    if summary_match:
        # Trim trailing separators/quotes the summary may pick up.
        summary = re.split(
            r"\s+(?:target_url|evidence_url|pr)\s*=",
            summary_match.group("summary"),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip().strip('"').strip()
    target_match = _TARGET_RE.search(body)
    evidence_match = _EVIDENCE_RE.search(body)
    return ParsedClaim(
        task_id=task_match.group("task"),
        status=status_match.group("status").lower(),  # type: ignore[arg-type]
        summary=summary,
        target_url=target_match.group("url") if target_match else None,
        evidence_url=evidence_match.group("url") if evidence_match else None,
    )


# --- TASKS.md parsing ------------------------------------------------------

_CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<body>.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<body>.+?)\s*$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(?P<body>.+?)\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<body>.+?)\s*$")
# A leading task id like "T3", "task-3", or "ABC-12" followed by a separator.
_ID_RE = re.compile(r"^\**\s*(?P<id>(?:[A-Za-z]+-\d+|[A-Za-z]\d+))\b[\s:.)\-–—]*")


def parse_tasks(text: str) -> list[BuilderTask]:
    """Parse a markdown TASKS.md into an ordered list of `BuilderTask`.

    The real Tasklight registry uses task headings (`### T1 — title`) followed by
    multiline requirements, so that format takes precedence and preserves the body as
    `details`. Checkbox items (`- [ ] ...` / `- [x] ...`), plain bullets, and numbered
    items remain supported for alternate registries. A leading task id (e.g. `T3`,
    `task-3`, `ABC-12`) is used when present; otherwise a positional id `T<n>` is
    synthesized for list items. A checked box marks a list task done.
    """
    heading_tasks = _parse_heading_tasks(text)
    if heading_tasks:
        return heading_tasks

    tasks: list[BuilderTask] = []
    for line in text.splitlines():
        done = False
        body: Optional[str] = None
        checkbox = _CHECKBOX_RE.match(line)
        if checkbox:
            done = checkbox.group("mark").lower() == "x"
            body = checkbox.group("body")
        else:
            for pattern in (_BULLET_RE, _NUMBERED_RE):
                found = pattern.match(line)
                if found:
                    body = found.group("body")
                    break
        if not body:
            continue
        task_id, title = _split_id_and_title(body, len(tasks) + 1)
        if not title:
            continue
        tasks.append(BuilderTask(id=task_id, title=title, done=done))
    return tasks


def _parse_heading_tasks(text: str) -> list[BuilderTask]:
    """Parse explicit task headings and the requirements beneath each heading."""
    lines = text.splitlines()
    headings: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if not heading:
            continue
        body = heading.group("body")
        id_match = _ID_RE.match(body)
        if not id_match:
            continue
        task_id = id_match.group("id")
        title = body[id_match.end():].strip().strip("*_`").strip()
        if title:
            headings.append((index, task_id, title))

    tasks: list[BuilderTask] = []
    for position, (start, task_id, title) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        detail_lines = lines[start + 1:end]
        while detail_lines and (
            not detail_lines[0].strip() or detail_lines[0].strip() == "---"
        ):
            detail_lines.pop(0)
        while detail_lines and (
            not detail_lines[-1].strip() or detail_lines[-1].strip() == "---"
        ):
            detail_lines.pop()
        tasks.append(
            BuilderTask(
                id=task_id,
                title=title,
                details="\n".join(detail_lines).strip(),
            )
        )
    return tasks


def _split_id_and_title(body: str, position: int) -> tuple[str, str]:
    """Pull an explicit leading id from a task line, else synthesize `T<position>`."""
    id_match = _ID_RE.match(body)
    if id_match:
        task_id = id_match.group("id")
        title = body[id_match.end():]
    else:
        task_id = f"T{position}"
        title = body
    title = title.strip().strip("*_`").strip()
    return task_id, title


def pick_task(tasks: list[BuilderTask], task_id: Optional[str] = None) -> BuilderTask:
    """Choose a task: the one matching `task_id` (case-insensitive), or the first
    not-yet-done task, or the first task. Raises `BuilderError` if none is available."""
    if not tasks:
        raise BuilderError("No tasks found in the task list.")
    if task_id:
        for task in tasks:
            if task.id.lower() == task_id.lower():
                return task
        raise BuilderError(f"Task {task_id!r} not found in the task list.")
    for task in tasks:
        if not task.done:
            return task
    return tasks[0]


class BuilderRunner:
    """Drives one Builder attempt: pick a task, invoke the real Guild agent, parse its
    claim, and submit it into the shared audit pipeline."""

    def __init__(
        self,
        auditor: Auditor,
        tiers: TierManager,
        bus: Optional[EventBus] = None,
        tasks_file: Optional[Path] = None,
        builder_agent_id: Optional[str] = None,
        log_path: Optional[Path] = None,
        timeout_s: float = DEFAULT_BUILDER_TIMEOUT_S,
        result_sink: Optional[ResultSink] = None,
    ) -> None:
        self._auditor = auditor
        self._tiers = tiers
        self._bus = bus
        self._tasks_file = tasks_file or config.tasks_file()
        self._builder_agent_id = builder_agent_id or config.BUILDER_AGENT_ID
        self._log_path = log_path or (config.state_dir() / "builder.jsonl")
        self._timeout_s = timeout_s
        # Optional callback so a host (the server) can capture the audited claim + result
        # into its own state; the CLI leaves it unset.
        self._result_sink = result_sink

    # -- tasks --------------------------------------------------------------

    def load_tasks(self) -> list[BuilderTask]:
        if not self._tasks_file.exists():
            raise BuilderError(
                f"Task list not found at {self._tasks_file}. Set TASKS_FILE or create "
                "target-app/TASKS.md."
            )
        return parse_tasks(self._tasks_file.read_text())

    # -- agent invocation ---------------------------------------------------

    def _guild_agent_for_tier(self) -> str:
        tier = self._tiers.get(self._builder_agent_id).tier
        return config.guild_builder_agent(tier)

    def _build_prompt(self, task: BuilderTask) -> str:
        # The Builder is never told about QA, verdicts, or tiers — independence is the
        # product. It is only asked to do the work and self-report a claim block.
        requirements = (
            f"\n\nTask requirements from TASKS.md:\n{task.details}" if task.details else ""
        )
        deployment = (
            "\n\nA done claim must name the live deployed acceptance surface as "
            "target_url=https://... . If the change is not deployed, report blocked."
            if config.builder_requires_deployed_target()
            else ""
        )
        return (
            "You are the CONFESSION Builder agent. Complete this task in the target "
            "application, making the change directly:\n"
            f"[{task.id}] {task.title}"
            f"{requirements}"
            f"{deployment}\n\n"
            "When you are finished, end your reply with EXACTLY one line:\n"
            f"[CLAIM task={task.id} status=done summary=<one sentence> "
            "target_url=<live URL> evidence_url=<PR or commit URL>]\n"
            "If you could not complete it, use status=blocked and explain in the summary."
        )

    async def invoke_agent(self, task: BuilderTask) -> str:
        """Run the real Guild builder agent once and return its stdout.

        Uses the pinned Guild CLI package from `GUILD_CLI_PACKAGE`. Raises
        `BuilderNotConfigured` when the CLI is missing or exits non-zero with no output
        (the unauthenticated/misconfigured case) — never fabricates a response.
        """
        agent = self._guild_agent_for_tier()
        prompt = self._build_prompt(task)
        cmd = [
            "npx",
            "--yes",
            config.GUILD_CLI_PACKAGE,
            "chat",
            "--once",
            prompt,
            "--agent",
            agent,
        ]

        if shutil.which("npx") is None:
            raise BuilderNotConfigured(
                "npx is not on PATH — install Node.js and the Guild CLI, then "
                f"`npx {config.GUILD_CLI_PACKAGE} auth login` before running the Builder."
            )

        def _run() -> tuple[int, str, str]:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout_s)
            return proc.returncode, proc.stdout or "", proc.stderr or ""

        try:
            returncode, stdout, stderr = await asyncio.to_thread(_run)
        except (FileNotFoundError, OSError) as exc:
            raise BuilderNotConfigured(f"Could not run the Guild CLI: {exc}") from exc
        except subprocess.SubprocessError as exc:
            raise BuilderNotConfigured(f"Guild CLI invocation failed: {exc}") from exc

        if returncode != 0:
            raise BuilderNotConfigured(
                f"Guild CLI exited {returncode}; the run cannot be trusted as complete. "
                f"stderr: {stderr.strip()[:400]}"
            )
        return stdout

    # -- full cycle ---------------------------------------------------------

    async def run(self, task_id: Optional[str] = None) -> dict[str, Any]:
        """Run one Builder attempt end to end.

        Returns an honest outcome dict. `status` is one of:
        * "audited"  — the agent claimed done; the claim ran the full audit pipeline
                       (includes claim_id, verdict, report_url).
        * "blocked"  — the agent honestly reported it could not finish; no audit.
        * "no_claim" — the agent produced no valid claim block; recorded, no audit.
        * "not_deployed" — a done claim named no live acceptance surface; no audit.
        * "rejected_claim" — the claim named the wrong task or a disallowed target.
        Raises `BuilderNotConfigured` if the real agent could not be run at all.
        """
        task = pick_task(self.load_tasks(), task_id)
        agent = self._guild_agent_for_tier()
        try:
            output = await self.invoke_agent(task)
        except BuilderNotConfigured as exc:
            self._log(
                {
                    "at": utcnow().isoformat(),
                    "status": "not_configured",
                    "task_id": task.id,
                    "guild_agent": agent,
                    "error": str(exc),
                }
            )
            raise
        parsed = parse_claim_block(output)

        base = {"task_id": task.id, "guild_agent": agent}

        if parsed is None:
            outcome = {**base, "status": "no_claim"}
            self._log({**outcome, "at": utcnow().isoformat(), "raw_output": output[:2000]})
            return outcome

        if parsed.task_id.casefold() != task.id.casefold():
            outcome = {
                **base,
                "status": "rejected_claim",
                "claimed_task_id": parsed.task_id,
                "reason": "The claim task id did not match the assigned task.",
            }
            self._log({**outcome, "at": utcnow().isoformat()})
            return outcome

        if parsed.status == "blocked":
            outcome = {**base, "task_id": parsed.task_id, "status": "blocked", "summary": parsed.summary}
            self._log({**outcome, "at": utcnow().isoformat()})
            return outcome

        if config.builder_requires_deployed_target() and not parsed.target_url:
            outcome = {
                **base,
                "status": "not_deployed",
                "summary": parsed.summary,
                "reason": "A live target_url is required before a done claim can be audited.",
            }
            self._log({**outcome, "at": utcnow().isoformat()})
            return outcome

        if parsed.target_url and not _target_url_allowed(parsed.target_url):
            outcome = {
                **base,
                "status": "rejected_claim",
                "claimed_task_id": parsed.task_id,
                "reason": "The claimed target_url host is not allowed.",
            }
            self._log({**outcome, "at": utcnow().isoformat()})
            return outcome

        # status == "done" -> a real claim enters the shared audit pipeline.
        claim = Claim(
            id=uuid.uuid4().hex,
            agent_id=self._builder_agent_id,
            task_id=parsed.task_id,
            text=parsed.summary or task.title,
            target_url=parsed.target_url,
        )
        if self._bus is not None:
            await self._bus.emit(
                EventType.CLAIM_SUBMITTED,
                claim_id=claim.id,
                agent_id=claim.agent_id,
                task_id=claim.task_id,
                claim_text=claim.text,
            )
        self._log(
            {
                "at": utcnow().isoformat(),
                "status": "submitted",
                "task_id": parsed.task_id,
                "guild_agent": agent,
                "claim_id": claim.id,
                "summary": parsed.summary,
                "target_url": parsed.target_url,
                "evidence_url": parsed.evidence_url,
            }
        )
        result = await self._auditor.audit(claim)
        if self._result_sink is not None:
            await self._result_sink(claim, result)
        return {
            **base,
            "task_id": parsed.task_id,
            "status": "audited",
            "claim_id": claim.id,
            "verdict": result.verdict.value,
            "report_url": result.report_url,
            "error": result.error,
        }

    def _log(self, record: dict[str, Any]) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")


def _target_url_allowed(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in (
            {"https"} if config.ENVIRONMENT == "production" else {"http", "https"}
        )
        and bool(parsed.hostname)
        and parsed.hostname.lower() in config.target_app_allowed_hosts()
    )

"""The evolution loop — caught lies become a real Pioneer LoRA fine-tune.

Every FALSE_CLAIM the auditor catches is appended to `engine/state/lies.jsonl` as a real
record (claim text + Replay's root-cause). `build_dataset` turns those records into
training examples that teach an agent to report honestly instead of over-claiming.
`run_finetune` drives the real Pioneer flow (generate dataset -> poll -> start LoRA
job -> poll) and appends every real response — job ids, statuses — to
`engine/state/training.jsonl`.

The server may start `run_finetune` automatically at the configured caught-lie threshold.
It requires PIONEER_API_KEY (a `PioneerClient` is constructed lazily); without it the
caller gets `PioneerNotConfigured`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

from . import config
from .events import EventBus
from .models import Claim, EventType, utcnow
from .pioneer_client import PioneerClient, is_success_state, job_id_of, job_state_of


class Trainer:
    """Accumulates caught lies and runs the Pioneer fine-tune over them."""

    def __init__(
        self,
        lies_path: Optional[Path] = None,
        training_path: Optional[Path] = None,
        bus: Optional[EventBus] = None,
        pioneer: Optional[PioneerClient] = None,
    ) -> None:
        state = config.state_dir()
        self._lies_path = lies_path or (state / "lies.jsonl")
        self._training_path = training_path or (state / "training.jsonl")
        self._bus = bus
        self._pioneer = pioneer
        self._lock: Optional[asyncio.Lock] = None

    def _active_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # -- caught-lie ledger --------------------------------------------------

    async def record_lie(self, claim: Claim, root_cause: str, report_url: Optional[str] = None) -> dict[str, Any]:
        """Append one caught false claim to the lies ledger and emit `lie_recorded`."""
        record = {
            "at": utcnow().isoformat(),
            "claim_id": claim.id,
            "task_id": claim.task_id,
            "agent_id": claim.agent_id,
            "text": claim.text,
            "root_cause": root_cause,
            "report_url": report_url,
        }
        async with self._active_lock():
            await asyncio.to_thread(_append_jsonl, self._lies_path, record)
        if self._bus is not None:
            # lie_recorded contract (ui/src/types.ts): {claim_id, agent_id, claim_text,
            # report_url?}. The ledger file keeps the richer record (root_cause, task_id).
            await self._bus.emit(
                EventType.LIE_RECORDED,
                claim_id=claim.id,
                agent_id=claim.agent_id,
                claim_text=claim.text,
                report_url=report_url,
            )
        return record

    def read_lies(self) -> list[dict[str, Any]]:
        """All caught-lie records (oldest first)."""
        return _read_jsonl(self._lies_path)

    def read_training_log(self) -> list[dict[str, Any]]:
        """All fine-tune responses recorded so far (oldest first)."""
        return _read_jsonl(self._training_path)

    # -- dataset ------------------------------------------------------------

    def build_dataset(self) -> list[dict[str, Any]]:
        """Convert the caught-lie ledger into Pioneer `/generate` training examples.

        Each example pairs the over-claiming assertion (the input the model produced) with
        the honest report it should have produced, grounded in Replay's real root-cause.
        The chat shape (`messages`) matches Pioneer's OpenAI-compatible decoder training.
        """
        examples: list[dict[str, Any]] = []
        for lie in self.read_lies():
            root_cause = lie.get("root_cause") or "Replay QA found the claimed work broken."
            examples.append(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Task {lie.get('task_id')}: report the completion status of your work."
                            ),
                        },
                        {
                            "role": "assistant",
                            "content": (
                                "Not complete. Independent QA found the claimed-done work broken. "
                                f"Root cause: {root_cause}"
                            ),
                        },
                    ],
                    "metadata": {
                        "claim_id": lie.get("claim_id"),
                        "agent_id": lie.get("agent_id"),
                        "report_url": lie.get("report_url"),
                    },
                }
            )
        return examples

    # -- fine-tune ----------------------------------------------------------

    def _client(self) -> PioneerClient:
        """Lazily build the Pioneer client. Raises PioneerNotConfigured without a key."""
        if self._pioneer is None:
            self._pioneer = PioneerClient()
        return self._pioneer

    async def run_finetune(
        self,
        base_model: str,
        dataset_name: Optional[str] = None,
        version: str = "v1",
    ) -> dict[str, Any]:
        """Run the real Pioneer fine-tune over the accumulated caught lies.

        Flow: build examples -> `POST /generate` -> poll -> `POST /felix/training-jobs`
        (LoRA) -> poll. Every real Pioneer response is appended to the training log and
        surfaced as a `training_status` event. Returns the terminal training-job status
        (its id is directly usable as PIONEER_MODEL).

        Raises `ValueError` if there are no caught lies yet, and `PioneerNotConfigured`
        (from the client) if PIONEER_API_KEY is unset.
        """
        examples = self.build_dataset()
        if not examples:
            raise ValueError("No caught lies recorded yet — nothing to fine-tune on.")
        client = self._client()
        await client.validate_base_model(base_model)
        name = dataset_name or f"confession-lies-{version}"

        async def _record(kind: str, response: Any) -> None:
            """Append every real Pioneer response to the training log (file only)."""
            entry = {"at": utcnow().isoformat(), "kind": kind, "response": response}
            await asyncio.to_thread(_append_jsonl, self._training_path, entry)

        # 1) Generate/register the dataset from the caught-lie examples. The generation
        # phase is logged to file but not surfaced as WS training events: the UI's job
        # model is keyed on the single fine-tune job id (below), which IS the model id.
        generate_response = await client.generate_dataset(name, examples)
        await _record("generate_started", generate_response)
        generate_job_id = job_id_of(generate_response)
        if generate_job_id:
            generate_final = await client.poll_job(
                client.get_generate_job,
                generate_job_id,
                on_status=lambda s: _record("generate_status", s),
            )
            await _record("generate_finished", generate_final)

        # 2) Start the LoRA fine-tune over that dataset — this job is THE training job.
        finetune_response = await client.start_finetune(
            dataset_name=name, version=version, base_model=base_model
        )
        await _record("finetune_started", finetune_response)
        finetune_job_id = job_id_of(finetune_response)
        if not finetune_job_id:
            return finetune_response

        # training_started contract (ui/src/types.ts): {job_id, base_model?, example_count?}.
        if self._bus is not None:
            await self._bus.emit(
                EventType.TRAINING_STARTED,
                job_id=finetune_job_id,
                base_model=base_model,
                example_count=len(examples),
            )

        async def _on_finetune_status(status: Any) -> None:
            await _record("finetune_status", status)
            if self._bus is not None:
                state = job_state_of(status)
                # When training completes, the job id IS the chat model id.
                model_id = finetune_job_id if is_success_state(state) else None
                await self._bus.emit(
                    EventType.TRAINING_STATUS,
                    job_id=finetune_job_id,
                    status=state,
                    model_id=model_id,
                )

        finetune_final = await client.poll_job(
            client.get_finetune_job, finetune_job_id, on_status=_on_finetune_status
        )
        await _record("finetune_finished", finetune_final)
        return finetune_final


# --- jsonl helpers ---------------------------------------------------------


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records

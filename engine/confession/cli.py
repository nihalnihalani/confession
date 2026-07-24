"""Command-line entry point — run one real audit cycle, or dump receipts.

    python -m confession.cli audit --claim "task-1 done" --target-url https://app.example
    python -m confession.cli audit --claim "..." --json
    python -m confession.cli receipts [--json]

`audit` runs the identical pipeline the server uses (create Replay project -> poll ->
verdict -> tier ratchet -> record lie) against live Replay/Guild and prints the verdict
plus the real receipt URLs. `receipts` prints the current durable state as JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any, Optional

from . import config
from .auditor import Auditor
from .builder import BuilderNotConfigured, BuilderRunner
from .events import Event, EventBus
from .models import Claim, Verdict
from .replay_client import ReplayClient, ReplayConfigError
from .tiers import TierManager
from .trainer import Trainer


async def _run_audit(claim_text: str, target_url: str, agent_id: str, task_id: str) -> dict[str, Any]:
    bus = EventBus()

    async def _print_event(event: Event) -> None:
        print(f"  · {event.type.value}", file=sys.stderr)

    # Mirror progress to stderr so --json keeps stdout clean.
    async def _drain() -> None:
        async with bus.subscribe(replay_history=False) as stream:
            async for event in stream:
                await _print_event(event)

    drain_task = asyncio.create_task(_drain())

    replay = ReplayClient()
    tiers = TierManager(bus=bus)
    trainer = Trainer(bus=bus)
    auditor = Auditor(bus=bus, replay=replay, tiers=tiers, trainer=trainer, target_url=target_url)

    claim = Claim(id=uuid.uuid4().hex, agent_id=agent_id, task_id=task_id, text=claim_text)
    result = await auditor.audit(claim)
    tier_state = tiers.get(agent_id)

    # Let the last events flush, then stop draining.
    await asyncio.sleep(0)
    drain_task.cancel()

    return {
        "claim": claim.model_dump(mode="json"),
        "verdict": result.verdict.value,
        "replay_project_id": result.replay_project_id,
        "report_url": result.report_url,
        "bugs": [bug.model_dump(mode="json") for bug in result.bugs],
        "error": result.error,
        "tier": tier_state.model_dump(mode="json"),
    }


def _cmd_audit(args: argparse.Namespace) -> int:
    target_url = args.target_url or config.TARGET_APP_URL
    if not target_url:
        print("error: --target-url or TARGET_APP_URL is required", file=sys.stderr)
        return 2
    try:
        outcome = asyncio.run(
            _run_audit(args.claim, target_url, args.agent_id, args.task_id)
        )
    except ReplayConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(outcome, indent=2))
    else:
        verdict = outcome["verdict"]
        print(f"VERDICT: {verdict}")
        if outcome["report_url"]:
            print(f"Replay report: {outcome['report_url']}")
        if outcome["replay_project_id"]:
            print(f"Replay project: {outcome['replay_project_id']}")
        if outcome["error"]:
            print(f"Infra error (PENDING, re-audit): {outcome['error']}")
        for bug in outcome["bugs"]:
            print(f"  - [{bug.get('severity')}] {bug.get('title')} :: {bug.get('url')}")
        tier = outcome["tier"]
        print(f"Tier: {tier['tier']} (streak {tier['streak']})")
    # A caught lie is a successful detection, not a program error: exit 0 for any reached
    # verdict; non-zero only when the audit could not run.
    return 0 if outcome["verdict"] in {v.value for v in Verdict} else 1


async def _run_builder(task_id: Optional[str], target_url: str) -> dict[str, Any]:
    bus = EventBus()

    async def _drain() -> None:
        async with bus.subscribe(replay_history=False) as stream:
            async for event in stream:
                print(f"  · {event.type.value}", file=sys.stderr)

    drain_task = asyncio.create_task(_drain())
    replay = ReplayClient()
    tiers = TierManager(bus=bus)
    trainer = Trainer(bus=bus)
    auditor = Auditor(bus=bus, replay=replay, tiers=tiers, trainer=trainer, target_url=target_url)
    runner = BuilderRunner(auditor=auditor, tiers=tiers, bus=bus)
    outcome = await runner.run(task_id)
    await asyncio.sleep(0)
    drain_task.cancel()
    return outcome


def _cmd_builder(args: argparse.Namespace) -> int:
    target_url = args.target_url or config.TARGET_APP_URL
    if not target_url:
        print("error: --target-url or TARGET_APP_URL is required", file=sys.stderr)
        return 2
    try:
        outcome = asyncio.run(_run_builder(args.task, target_url))
    except ReplayConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BuilderNotConfigured as exc:
        print(f"error: builder not configured — {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(outcome, indent=2))
    else:
        status = outcome.get("status")
        print(f"BUILDER: {status}  (task {outcome.get('task_id')}, agent {outcome.get('guild_agent')})")
        if status == "audited":
            print(f"  claim: {outcome.get('claim_id')}")
            print(f"  VERDICT: {outcome.get('verdict')}")
            if outcome.get("report_url"):
                print(f"  Replay report: {outcome['report_url']}")
            if outcome.get("error"):
                print(f"  Infra error (PENDING, re-audit): {outcome['error']}")
        elif status == "blocked":
            print(f"  agent reported blocked: {outcome.get('summary')}")
        elif status == "no_claim":
            print("  agent produced no valid [CLAIM ...] block; nothing audited")
    return 0


def _cmd_receipts(args: argparse.Namespace) -> int:
    tiers = TierManager()
    trainer = Trainer()
    receipts = {
        "tiers": {
            agent_id: tier.model_dump(mode="json")
            for agent_id, tier in tiers.all_states().items()
        },
        "lies": trainer.read_lies(),
        "training": trainer.read_training_log(),
    }
    print(json.dumps(receipts, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confession", description="CONFESSION engine CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="run one full real audit cycle")
    audit.add_argument("--claim", required=True, help="the completion claim text to audit")
    audit.add_argument("--target-url", default=None, help="deployed app URL (or TARGET_APP_URL)")
    audit.add_argument("--agent-id", default="builder", help="claiming agent id")
    audit.add_argument("--task-id", default="task", help="task id the claim refers to")
    audit.add_argument("--json", action="store_true", help="emit the outcome as JSON")
    audit.set_defaults(func=_cmd_audit)

    builder = sub.add_parser("builder", help="run one autonomous Builder attempt end to end")
    builder.add_argument("--task", default=None, help="task id to attempt (default: first not-done)")
    builder.add_argument("--target-url", default=None, help="deployed app URL (or TARGET_APP_URL)")
    builder.add_argument("--json", action="store_true", help="emit the outcome as JSON")
    builder.set_defaults(func=_cmd_builder)

    receipts = sub.add_parser("receipts", help="print current receipts state as JSON")
    receipts.add_argument("--json", action="store_true", help="(default) JSON output")
    receipts.set_defaults(func=_cmd_receipts)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

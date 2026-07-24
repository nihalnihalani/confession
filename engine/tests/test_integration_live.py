"""Live integration test — real Replay round-trip. Skipped unless keys are present.

This is the only test that touches the network. It runs a full real audit cycle against
the configured target app and asserts a real verdict was reached (VERIFIED / FALSE_CLAIM),
or that a genuine infra condition surfaced as PENDING. It never asserts a specific bug —
the target app's real state decides that.

Run with:  REPLAY_API_TOKEN=lqa_... TARGET_APP_URL=https://... pytest engine/tests -q
"""

import os
import uuid

import pytest

from confession.auditor import Auditor
from confession.events import EventBus
from confession.models import Claim, Verdict
from confession.tiers import TierManager
from confession.trainer import Trainer

pytestmark = pytest.mark.skipif(
    not (os.getenv("REPLAY_API_TOKEN") and os.getenv("TARGET_APP_URL")),
    reason="live keys required (REPLAY_API_TOKEN + TARGET_APP_URL)",
)


@pytest.mark.asyncio
async def test_real_audit_cycle_reaches_a_verdict(tmp_path):
    from confession.replay_client import ReplayClient

    bus = EventBus()
    tiers = TierManager(state_path=tmp_path / "tiers.json", bus=bus)
    trainer = Trainer(
        lies_path=tmp_path / "lies.jsonl",
        training_path=tmp_path / "training.jsonl",
        bus=bus,
    )
    auditor = Auditor(
        bus=bus,
        replay=ReplayClient(),
        tiers=tiers,
        trainer=trainer,
        target_url=os.environ["TARGET_APP_URL"],
    )
    claim = Claim(
        id=uuid.uuid4().hex,
        agent_id="builder",
        task_id="live-smoke",
        text="the app's main flow works end to end",
    )
    result = await auditor.audit(claim)
    assert result.verdict in {Verdict.VERIFIED, Verdict.FALSE_CLAIM, Verdict.PENDING}
    if result.verdict is not Verdict.PENDING:
        # a real audit that reached a verdict must carry the Replay project it ran against
        assert result.replay_project_id is not None

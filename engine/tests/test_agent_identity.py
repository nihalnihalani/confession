"""Tests for the agent-identity gate — allowlist parsing (pure) and the server's 403
enforcement. Judge identities are always allowed to submit but are exercised elsewhere for
the never-ratchet rule; here we assert they pass the submission gate."""

import asyncio

from fastapi.testclient import TestClient

from confession import config
from confession.auditor import Auditor
from confession.events import EventBus
from confession.models import BugFinding, Claim, Verdict
from confession.server import app
from confession.tiers import TierManager
from confession.trainer import Trainer


# --- pure config helpers ---------------------------------------------------


def test_allowed_agents_none_when_unset(monkeypatch):
    monkeypatch.delenv("CONFESSION_ALLOWED_AGENTS", raising=False)
    assert config.allowed_agents() is None


def test_allowed_agents_parses_and_trims(monkeypatch):
    monkeypatch.setenv("CONFESSION_ALLOWED_AGENTS", " builder , confession-builder ,")
    assert config.allowed_agents() == {"builder", "confession-builder"}


def test_judge_agents_default_and_override(monkeypatch):
    monkeypatch.delenv("CONFESSION_JUDGE_AGENTS", raising=False)
    assert config.judge_agents() == {"judge"}
    assert config.is_judge_agent("judge") is True
    monkeypatch.setenv("CONFESSION_JUDGE_AGENTS", "judge, referee")
    assert config.judge_agents() == {"judge", "referee"}
    assert config.is_judge_agent("referee") is True
    assert config.is_judge_agent("builder") is False


# --- server enforcement ----------------------------------------------------


def _post(agent_id: str):
    client = TestClient(app)
    return client.post(
        "/api/claims", json={"agent_id": agent_id, "task_id": "t1", "claim_text": "done"}
    )


def test_unknown_agent_rejected_when_allowlist_set(monkeypatch):
    monkeypatch.setattr(config, "TARGET_APP_URL", "http://target.example")
    monkeypatch.setenv("CONFESSION_ALLOWED_AGENTS", "builder")
    resp = _post("hacker")
    assert resp.status_code == 403
    assert "not permitted" in resp.json()["detail"]


def test_allowed_agent_passes_the_gate(monkeypatch):
    monkeypatch.setattr(config, "TARGET_APP_URL", "http://target.example")
    monkeypatch.setenv("CONFESSION_ALLOWED_AGENTS", "builder")
    # passes the identity gate (a later 503 for unconfigured Replay is fine — not 403)
    assert _post("builder").status_code != 403


def test_judge_always_passes_the_gate(monkeypatch):
    monkeypatch.setattr(config, "TARGET_APP_URL", "http://target.example")
    monkeypatch.setenv("CONFESSION_ALLOWED_AGENTS", "builder")  # judge NOT listed
    assert _post("judge").status_code != 403


def test_no_allowlist_accepts_any_agent(monkeypatch):
    monkeypatch.setattr(config, "TARGET_APP_URL", "http://target.example")
    monkeypatch.delenv("CONFESSION_ALLOWED_AGENTS", raising=False)
    assert _post("anyone-at-all").status_code != 403


# --- judge-never-ratchet rule ----------------------------------------------


class RecordingReplay:
    """An in-memory Replay collaborator for driving the auditor without a network. Returns
    whatever bugs it is constructed with; not part of the shipped product."""

    def __init__(self, bugs):
        self._bugs = bugs

    async def find_project_by_name(self, _name):
        return None

    async def create_project(self, **kwargs):
        return {"project_id": "p1", "url": "https://app.replay.io/project/p1"}

    async def poll_until_finished(self, project_id, on_progress=None, **kwargs):
        if on_progress is not None:
            await on_progress({"bugs": len(self._bugs)})
        return {"finished_at": "now"}

    async def fetch_bugs(self, project_id, status="open"):
        return list(self._bugs)


def _auditor(tmp_path, bugs):
    bus = EventBus()
    tiers = TierManager(state_path=tmp_path / "tiers.json", bus=bus, ratchet_n=3)
    trainer = Trainer(
        lies_path=tmp_path / "lies.jsonl", training_path=tmp_path / "training.jsonl", bus=bus
    )
    auditor = Auditor(
        bus=bus,
        replay=RecordingReplay(bugs),
        tiers=tiers,
        trainer=trainer,
        target_url="http://target.example",
    )
    return auditor, tiers, trainer


def test_builder_verdict_advances_its_tier(tmp_path):
    async def scenario():
        auditor, tiers, _ = _auditor(tmp_path, bugs=[])
        claim = Claim(id="c1", task_id="t1", agent_id="builder", text="finished the checkout page")
        result = await auditor.audit(claim)
        assert result.verdict is Verdict.VERIFIED
        assert tiers.get("builder").streak == 1

    asyncio.run(scenario())


def test_judge_verdict_never_moves_a_tier(tmp_path):
    async def scenario():
        auditor, tiers, _ = _auditor(tmp_path, bugs=[])
        claim = Claim(id="c1", task_id="t1", agent_id="judge", text="it is done")
        result = await auditor.audit(claim)
        assert result.verdict is Verdict.VERIFIED
        # judge identity's tier is untouched — no streak, no history
        judge_state = tiers.get("judge")
        assert judge_state.streak == 0
        assert judge_state.history == []

    asyncio.run(scenario())


def test_judge_false_claim_records_no_lie(tmp_path):
    async def scenario():
        bug = BugFinding(title="broken", root_cause="the flow crashes")
        auditor, tiers, trainer = _auditor(tmp_path, bugs=[bug])
        # unscoped claim (no usable scope tokens) -> the bug counts -> FALSE_CLAIM
        claim = Claim(id="c1", task_id="", agent_id="judge", text="it is done")
        result = await auditor.audit(claim)
        assert result.verdict is Verdict.FALSE_CLAIM
        # a judge's deliberate false claim never demotes and never feeds the ledger
        assert tiers.get("judge").tier == 0
        assert trainer.read_lies() == []

    asyncio.run(scenario())


def test_audit_reuses_deterministic_replay_project(tmp_path):
    class ExistingProjectReplay(RecordingReplay):
        def __init__(self):
            super().__init__([])
            self.created = False

        async def find_project_by_name(self, name):
            assert name == "confession-c-existing"
            return {
                "id": "p-existing",
                "name": name,
                "url": "https://app.replay.io/project/p-existing",
            }

        async def create_project(self, **kwargs):
            self.created = True
            raise AssertionError("an existing claim project must be reused")

    async def scenario():
        replay = ExistingProjectReplay()
        checkpoints = []
        bus = EventBus()
        auditor = Auditor(
            bus=bus,
            replay=replay,
            tiers=TierManager(state_path=tmp_path / "tiers.json", bus=bus),
            trainer=Trainer(
                lies_path=tmp_path / "lies.jsonl",
                training_path=tmp_path / "training.jsonl",
                bus=bus,
            ),
            target_url="http://target.example",
            result_checkpoint=lambda claim, result: _capture_checkpoint(
                checkpoints, claim.id, result.replay_project_id
            ),
        )
        claim = Claim(
            id="c-existing",
            task_id="T1",
            agent_id="builder",
            text="due date is complete",
        )
        result = await auditor.audit(claim)
        assert result.verdict is Verdict.VERIFIED
        assert result.replay_project_id == "p-existing"
        assert replay.created is False
        assert checkpoints == [("c-existing", "p-existing")]

    asyncio.run(scenario())


async def _capture_checkpoint(checkpoints, claim_id, project_id):
    checkpoints.append((claim_id, project_id))

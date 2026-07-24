"""Durability, idempotency, job recovery, and rate-control tests."""

from confession.models import AuditResult, Claim, Event, EventType, Verdict
from confession.state import StateStore


def test_claim_result_and_events_survive_reopen(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = StateStore(path)
    claim = Claim(id="c1", agent_id="builder", task_id="T1", text="done")
    result = AuditResult(claim_id="c1", verdict=Verdict.PENDING, error="network")
    event = Event(type=EventType.CLAIM_SUBMITTED, payload={"claim_id": "c1"})
    store.save_claim(claim, result)
    store.append_event(event)
    store.close()

    reopened = StateStore(path)
    claims, results = reopened.load_claims()
    assert claims["c1"].task_id == "T1"
    assert results["c1"].error == "network"
    assert reopened.load_events()[0].payload["claim_id"] == "c1"


def test_reaudit_attempt_budget_is_atomic(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.save_claim(Claim(id="c1", agent_id="builder", task_id="T1", text="done"))
    assert store.increment_reaudit_attempt("c1", 2) == 1
    assert store.increment_reaudit_attempt("c1", 2) == 2
    assert store.increment_reaudit_attempt("c1", 2) is None
    assert store.reaudit_attempts("c1") == 2


def test_job_and_idempotency_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.create_job("j1", "audit", {"claim_id": "c1"})
    assert store.recoverable_jobs()[0]["id"] == "j1"
    store.update_job("j1", "succeeded", {"verdict": "VERIFIED"})
    assert store.get_job("j1")["result"]["verdict"] == "VERIFIED"
    assert store.recoverable_jobs() == []

    first = store.put_idempotent("claims", "key-1", {"claim_id": "c1"})
    second = store.put_idempotent("claims", "key-1", {"claim_id": "c2"})
    assert first == second == {"claim_id": "c1"}


def test_rate_limit_enforces_window(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    assert store.consume_rate("judge:127.0.0.1", 2) is True
    assert store.consume_rate("judge:127.0.0.1", 2) is True
    assert store.consume_rate("judge:127.0.0.1", 2) is False

"""Guards the engine's emitted shapes against the authoritative UI contract
(ui/src/types.ts). Pure mappers only — no network, no keys."""

from confession.auditor import _progress_message
from confession.models import BugFinding, tier_label
from confession.server import ClaimRequest, _job_id_from_status, _pioneer_receipts


def test_bug_to_contract_has_exact_keys():
    bug = BugFinding(title="checkout 500", severity="high", root_cause="null tax", url="u", bug_id="b1")
    contract = bug.to_contract()
    assert set(contract.keys()) == {"id", "title", "severity", "root_cause", "url"}
    assert contract == {
        "id": "b1",
        "title": "checkout 500",
        "severity": "high",
        "root_cause": "null tax",
        "url": "u",
    }


def test_bug_to_contract_labels_missing_metadata_without_inventing():
    bug = BugFinding(title="only a title")
    contract = bug.to_contract()
    assert contract["severity"] == "unknown"  # labeled, not invented into a real severity
    assert contract["root_cause"] == ""
    assert contract["id"] is None
    assert contract["url"] is None


def test_tier_label_matches_ui_tier_strings():
    assert tier_label(0) == "L0"
    assert tier_label(1) == "L1"


def test_claim_request_uses_claim_text():
    body = ClaimRequest.model_validate({"agent_id": "a", "task_id": "t", "claim_text": "done"})
    assert body.claim_text == "done"


def test_claim_request_accepts_text_alias():
    body = ClaimRequest.model_validate({"agent_id": "a", "task_id": "t", "text": "done"})
    assert body.claim_text == "done"


def test_progress_message_summarizes_counts():
    message = _progress_message({"journeys": 2, "bugs": 1})
    assert "2 journeys" in message
    assert "1 bug" in message and "1 bugs" not in message  # singular pluralization


def test_progress_message_handles_empty_status():
    assert _progress_message({}) == "Replay QA running…"


def test_pioneer_receipts_shape_and_model_id_on_success():
    log = [
        {"at": "t0", "kind": "finetune_started", "response": {"id": "job-9"}},
        {"at": "t1", "kind": "finetune_status", "response": {"id": "job-9", "status": "running"}},
        {"at": "t2", "kind": "finetune_finished", "response": {"id": "job-9", "status": "succeeded"}},
    ]
    receipts = _pioneer_receipts(log)
    assert len(receipts) == 1
    row = receipts[0]
    assert row["job_id"] == "job-9"
    assert row["status"] == "succeeded"
    # the job id IS the model id once training succeeds
    assert row["model_id"] == "job-9"
    assert row["started_at"] == "t0"


def test_pioneer_receipts_no_model_id_while_running():
    log = [
        {"at": "t0", "kind": "finetune_started", "response": {"id": "job-1"}},
        {"at": "t1", "kind": "finetune_status", "response": {"id": "job-1", "status": "running"}},
    ]
    row = _pioneer_receipts(log)[0]
    assert row["status"] == "running"
    assert "model_id" not in row


def test_pioneer_receipts_ignores_generate_phase():
    log = [
        {"at": "t0", "kind": "generate_started", "response": {"id": "gen-1"}},
        {"at": "t1", "kind": "generate_status", "response": {"id": "gen-1", "status": "running"}},
    ]
    assert _pioneer_receipts(log) == []


def test_job_id_from_status_variants():
    assert _job_id_from_status({"job_id": "x"}) == "x"
    assert _job_id_from_status({"training_job_id": "y"}) == "y"
    assert _job_id_from_status({}) is None

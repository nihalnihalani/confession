"""Unit tests for the Builder loop's pure logic — claim-block parsing and task parsing.
No network, no subprocess: only the pure parsers and task selection."""

import pytest

from confession import config
from confession.builder import (
    BuilderError,
    BuilderTask,
    parse_claim_block,
    parse_tasks,
    pick_task,
)


# --- [CLAIM ...] block parsing ---------------------------------------------


def test_parse_valid_done_claim():
    text = "I made the change.\n[CLAIM task=T3 status=done summary=Added due dates to todos]\nthanks"
    claim = parse_claim_block(text)
    assert claim is not None
    assert claim.task_id == "T3"
    assert claim.status == "done"
    assert claim.summary == "Added due dates to todos"


def test_parse_blocked_claim():
    claim = parse_claim_block("[CLAIM task=T4 status=blocked summary=Could not find the module]")
    assert claim is not None
    assert claim.status == "blocked"
    assert claim.task_id == "T4"


def test_parse_is_case_insensitive():
    claim = parse_claim_block("[claim TASK=T3 STATUS=DONE summary=ok]")
    assert claim is not None
    assert claim.status == "done"
    assert claim.task_id == "T3"


def test_parse_multiline_summary():
    text = "[CLAIM task=T7 status=done summary=Reworked the flow\nand fixed the redirect]"
    claim = parse_claim_block(text)
    assert claim is not None
    assert "Reworked the flow" in claim.summary
    assert "fixed the redirect" in claim.summary


def test_parse_no_block_returns_none():
    assert parse_claim_block("I finished the task, all good.") is None


def test_parse_empty_returns_none():
    assert parse_claim_block("") is None
    assert parse_claim_block(None) is None  # type: ignore[arg-type]


def test_parse_malformed_missing_status_returns_none():
    assert parse_claim_block("[CLAIM task=T3 summary=hi]") is None


def test_parse_malformed_missing_task_returns_none():
    assert parse_claim_block("[CLAIM status=done summary=hi]") is None


def test_parse_ignores_surrounding_prose_and_extra_brackets():
    text = "steps: [1] did x [2] did y\n[CLAIM task=T1 status=done summary=done it]"
    claim = parse_claim_block(text)
    assert claim is not None
    assert claim.task_id == "T1"


def test_parse_hyphenated_task_id():
    claim = parse_claim_block("[CLAIM task=task-12 status=done summary=x]")
    assert claim is not None
    assert claim.task_id == "task-12"


# --- TASKS.md parsing ------------------------------------------------------


def test_parse_checkbox_tasks_with_ids():
    text = """
# Tasks
- [ ] T1: Add a login page
- [x] T2 — Wire the API
- [ ] task-3: Fix the footer
"""
    tasks = parse_tasks(text)
    assert [t.id for t in tasks] == ["T1", "T2", "task-3"]
    assert tasks[0].title == "Add a login page"
    assert tasks[1].done is True
    assert tasks[0].done is False
    assert tasks[2].id == "task-3"


def test_parse_synthesizes_id_when_absent():
    text = "- Build the dashboard\n- Ship the docs"
    tasks = parse_tasks(text)
    assert [t.id for t in tasks] == ["T1", "T2"]
    assert tasks[0].title == "Build the dashboard"


def test_parse_numbered_and_skips_non_task_lines():
    text = "## Heading\n1. First thing\nsome prose\n2. Second thing"
    tasks = parse_tasks(text)
    assert [t.title for t in tasks] == ["First thing", "Second thing"]


def test_parse_strips_markdown_emphasis():
    tasks = parse_tasks("- [ ] **T5** build the thing")
    assert tasks[0].id == "T5"
    assert tasks[0].title == "build the thing"


def test_parse_empty_document():
    assert parse_tasks("") == []


# --- task selection --------------------------------------------------------


def _tasks():
    return [
        BuilderTask(id="T1", title="a", done=True),
        BuilderTask(id="T2", title="b", done=False),
        BuilderTask(id="T3", title="c", done=False),
    ]


def test_pick_task_by_id_case_insensitive():
    assert pick_task(_tasks(), "t3").id == "T3"


def test_pick_task_defaults_to_first_not_done():
    assert pick_task(_tasks(), None).id == "T2"


def test_pick_task_all_done_returns_first():
    tasks = [BuilderTask(id="T1", title="a", done=True)]
    assert pick_task(tasks, None).id == "T1"


def test_pick_task_unknown_id_raises():
    with pytest.raises(BuilderError):
        pick_task(_tasks(), "T99")


def test_pick_task_empty_raises():
    with pytest.raises(BuilderError):
        pick_task([], None)


# --- tier-aware Guild agent selection --------------------------------------


def test_guild_builder_agent_l0_and_l1_derivation():
    l0 = config.guild_builder_agent(0)
    l1 = config.guild_builder_agent(1)
    assert l0.endswith("l0")
    # L1 swaps the l0 marker for l1 so a promoted builder runs with the write grant
    assert l1.endswith("l1")
    assert l1 == l0.replace("l0", "l1")

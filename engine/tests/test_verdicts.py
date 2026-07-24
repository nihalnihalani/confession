"""Unit tests for the pure verdict logic — every branch, no network."""

from confession.models import AuditResult, BugFinding, Claim, Verdict
from confession.verdicts import bug_in_scope, decide_verdict, in_scope_bugs, scope_tokens


def _claim(text: str = "task-7 done", task_id: str = "task-7") -> Claim:
    return Claim(id="c1", task_id=task_id, agent_id="builder", text=text)


def _audit(bugs=None, error=None) -> AuditResult:
    return AuditResult(claim_id="c1", bugs=bugs or [], error=error)


def test_verified_when_no_bugs_and_no_error():
    assert decide_verdict(_claim(), _audit()) is Verdict.VERIFIED


def test_false_claim_when_in_scope_bug_present():
    claim = _claim("finished the todos list at api/todos", task_id="task-7")
    bug = BugFinding(title="api/todos returns 500", root_cause="handler throws on empty body")
    assert decide_verdict(claim, _audit(bugs=[bug])) is Verdict.FALSE_CLAIM


def test_pending_on_infra_error_even_with_bugs():
    bug = BugFinding(title="anything", root_cause="whatever")
    verdict = decide_verdict(_claim(), _audit(bugs=[bug], error="Replay 503"))
    assert verdict is Verdict.PENDING


def test_pending_on_infra_error_with_no_bugs():
    assert decide_verdict(_claim(), _audit(error="timeout")) is Verdict.PENDING


def test_scope_tokens_include_task_id_and_meaningful_words():
    tokens = scope_tokens(_claim("Implemented the checkout flow", task_id="task-9"))
    assert "task-9" in tokens
    assert "checkout" in tokens
    assert "flow" in tokens
    # stop words and short words are excluded
    assert "the" not in tokens


def test_scope_tokens_keep_file_like_identifiers():
    tokens = scope_tokens(_claim("fixed src/list.tsx render", task_id="t1"))
    assert "src/list.tsx" in tokens


def test_bug_out_of_scope_yields_verified():
    claim = _claim("added the checkout button", task_id="task-9")
    # bug is about an unrelated area; none of the scope tokens appear
    bug = BugFinding(title="profile avatar missing", root_cause="broken image url on settings")
    assert bug_in_scope(claim, bug) is False
    assert decide_verdict(claim, _audit(bugs=[bug])) is Verdict.VERIFIED


def test_unscoped_claim_counts_every_bug():
    # A claim whose only tokens are stop/short words yields no scope tokens -> all bugs count.
    claim = _claim("it is done now", task_id="")
    assert scope_tokens(claim) == set()
    bug = BugFinding(title="some failure", root_cause="somewhere")
    assert bug_in_scope(claim, bug) is True
    assert decide_verdict(claim, _audit(bugs=[bug])) is Verdict.FALSE_CLAIM


def test_in_scope_bugs_filters_mixed_list():
    claim = _claim("finished checkout", task_id="task-9")
    hit = BugFinding(title="checkout total wrong", root_cause="tax rounding")
    miss = BugFinding(title="footer link 404", root_cause="stale route")
    scoped = in_scope_bugs(claim, [hit, miss])
    assert scoped == [hit]


# --- word-boundary scope matching (regression) -----------------------------


def test_task_id_does_not_substring_match_longer_word():
    # "t1" must NOT match "test1" — the old substring match wrongly demoted this.
    claim = _claim("did the work", task_id="t1")
    bug = BugFinding(title="test1 harness flaky", root_cause="unrelated to t1's scope")
    # note: root_cause mentions "t1's" -> "t1" on a word boundary, so it IS in scope here;
    # use a bug that only contains the longer word to prove no spurious match:
    bug_no_boundary = BugFinding(title="test1 harness flaky", root_cause="the testing rig")
    assert bug_in_scope(claim, bug_no_boundary) is False
    assert decide_verdict(claim, _audit(bugs=[bug_no_boundary])) is Verdict.VERIFIED


def test_task_id_does_not_match_numeric_extension():
    # "t1" must NOT match "t10".
    claim = _claim("did the work", task_id="t1")
    bug = BugFinding(title="t10 endpoint broken", root_cause="t10 handler throws")
    assert bug_in_scope(claim, bug) is False
    assert decide_verdict(claim, _audit(bugs=[bug])) is Verdict.VERIFIED


def test_task_id_matches_on_word_boundary():
    claim = _claim("did the work", task_id="t1")
    bug = BugFinding(title="t1 endpoint broken", root_cause="handler for t1 throws 500")
    assert bug_in_scope(claim, bug) is True
    assert decide_verdict(claim, _audit(bugs=[bug])) is Verdict.FALSE_CLAIM


def test_hyphenated_task_id_matches_whole_token():
    claim = _claim("did it", task_id="task-9")
    hit = BugFinding(title="task-9 flow fails", root_cause="regression in task-9")
    miss = BugFinding(title="task-90 flow fails", root_cause="different task-90")
    assert bug_in_scope(claim, hit) is True
    assert bug_in_scope(claim, miss) is False


def test_descriptive_words_still_substring_match():
    # Longer descriptive tokens keep substring behavior (checkout in checkouts).
    claim = _claim("finished the checkout page", task_id="t1")
    bug = BugFinding(title="checkouts list empty", root_cause="query returns nothing")
    assert bug_in_scope(claim, bug) is True


def test_trailing_punctuation_stripped_from_identifier():
    claim = _claim("fixed api/todos.", task_id="t1")
    bug = BugFinding(title="api/todos returns 500", root_cause="null body")
    assert bug_in_scope(claim, bug) is True

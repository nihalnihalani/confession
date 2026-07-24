"""Pure verdict logic — no network, no IO, fully unit-testable.

The rules (CLAUDE.md, non-negotiable):
* PENDING     — the audit hit a Replay infra error (timeout/5xx/network). A PENDING
                claim never changes an agent's tier; it is re-audited later.
* FALSE_CLAIM — Replay found open bugs within the claim's scope (the claimed-done work
                is broken).
* VERIFIED    — Replay's exploration finished with zero open bugs in the claim's scope.

"Scope" ties a claim to the bugs that count against it. A claim references a task and,
often, an area/file; a bug counts if the claim's scope tokens appear in the bug's title
or root-cause text. When a claim provides no usable scope tokens, every open bug counts
(the conservative reading — an unscoped "it's done" is answerable by any open bug).
"""

from __future__ import annotations

import re

from .models import AuditResult, BugFinding, Claim, Verdict

# Tokens too generic to scope a claim by (kept lowercase).
_STOP_TOKENS = frozenset(
    {
        "the", "and", "for", "with", "task", "done", "complete", "completed", "fix",
        "fixed", "add", "added", "update", "updated", "make", "works", "working", "now",
        "this", "that", "should", "when", "from", "into", "your", "have", "been", "page",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")


def scope_tokens(claim: Claim) -> set[str]:
    """The lowercased tokens that define a claim's scope, split by how they must match.

    Returns the union used by callers that don't care about match style. Internally the
    tokens are partitioned (see `_scope_token_groups`): the task_id and other short
    identifier-like tokens require whole-word matches (so `t1` never matches `test1` or
    `t10`), while longer descriptive words match as substrings.
    """
    word, substring = _scope_token_groups(claim)
    return word | substring


def _scope_token_groups(claim: Claim) -> tuple[set[str], set[str]]:
    """Partition a claim's scope tokens into (word_boundary, substring) match groups.

    * word_boundary — the task_id plus any file-like/identifier token. These are matched
      with `\\btoken\\b` so a short id like `t1` cannot spuriously match `test1`/`t10`,
      which previously caused false FALSE_CLAIM demotions.
    * substring — descriptive words from the claim text (length > 3, not a stop word),
      matched by containment because natural-language words tolerate it.
    """
    word: set[str] = set()
    substring: set[str] = set()
    if claim.task_id:
        word.add(claim.task_id.strip("./-_").lower())
    for raw in _TOKEN_RE.findall(claim.text or ""):
        # Strip leading/trailing separators picked up from prose ("todos." -> "todos")
        # so they don't break the word-boundary match on the real identifier.
        token = raw.strip("./-_").lower()
        if not token:
            continue
        if any(ch in token for ch in "/._-"):
            # file-like / compound identifiers: match as whole tokens
            word.add(token)
        elif len(token) > 3 and token not in _STOP_TOKENS:
            substring.add(token)
    word.discard("")
    substring.discard("")
    return word, substring


def bug_in_scope(claim: Claim, bug: BugFinding) -> bool:
    """True if `bug` falls within `claim`'s scope.

    A bug is in scope when a whole-word scope token (task_id / identifier) matches on a
    word boundary, or a descriptive scope token appears as a substring, in the bug's
    title or root-cause text (case-insensitive). If the claim yields no scope tokens at
    all, every bug is in scope.
    """
    word, substring = _scope_token_groups(claim)
    if not word and not substring:
        return True
    haystack = f"{bug.title or ''} {bug.root_cause or ''}".lower()
    if any(token in haystack for token in substring):
        return True
    return any(re.search(rf"\b{re.escape(token)}\b", haystack) for token in word)


def in_scope_bugs(claim: Claim, bugs: list[BugFinding]) -> list[BugFinding]:
    """Subset of `bugs` that count against `claim`."""
    return [bug for bug in bugs if bug_in_scope(claim, bug)]


def decide_verdict(claim: Claim, audit: AuditResult) -> Verdict:
    """Compute the verdict for `claim` from its `audit` result.

    Infra error wins first (PENDING). Otherwise, open bugs in the claim's scope mean
    FALSE_CLAIM; none means VERIFIED. This function is pure: it reads only `audit.error`
    and `audit.bugs` and never mutates its inputs.
    """
    if audit.error:
        return Verdict.PENDING
    if in_scope_bugs(claim, audit.bugs):
        return Verdict.FALSE_CLAIM
    return Verdict.VERIFIED

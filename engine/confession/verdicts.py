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
    """The lowercased tokens that define a claim's scope.

    Always includes the `task_id` (a claim is anchored to its task). Adds meaningful
    words from the claim text: length > 3, not a stop token — plus any token that looks
    file-like (contains `/`, `.`, `_`, or `-`), which is kept regardless of length
    because identifiers like `api/todos` or `list.tsx` are strong scope signals.
    """
    tokens: set[str] = set()
    if claim.task_id:
        tokens.add(claim.task_id.lower())
    for raw in _TOKEN_RE.findall(claim.text or ""):
        token = raw.lower()
        file_like = any(ch in token for ch in "/._-")
        if file_like or (len(token) > 3 and token not in _STOP_TOKENS):
            tokens.add(token)
    tokens.discard("")
    return tokens


def bug_in_scope(claim: Claim, bug: BugFinding) -> bool:
    """True if `bug` falls within `claim`'s scope.

    A bug is in scope when any of the claim's scope tokens appears (case-insensitive) in
    the bug's title or root-cause text. If the claim yields no scope tokens at all, every
    bug is in scope.
    """
    tokens = scope_tokens(claim)
    if not tokens:
        return True
    haystack = f"{bug.title or ''} {bug.root_cause or ''}".lower()
    return any(token in haystack for token in tokens)


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

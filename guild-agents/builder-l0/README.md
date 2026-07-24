# confession-builder-l0 — Builder, observation tier

`@guildai/confession~confession-builder-l0`

The Builder agent at its lowest tier. It reads task issues and repo source and can attest
only to work that is already present on the deployed acceptance surface. It cannot turn a
proposed change into completed work.

## The boundary is the grant, not the prompt

L0 is granted only read tools:

- `github_issues_get`, `github_issues_list_for_repo`, `github_issues_list_comments_for_repo`
- `github_repos_get_content`
- `guild_get_me`

There is no `create_comment`, no `create_or_update_file_contents`, no `pulls_create` in its toolset. **L0 physically cannot write — the boundary is the grant, not the prompt.** No jailbreak, prompt-injection, or model mistake can make it commit code, because the capability was never handed to it by Guild. The system prompt describes the boundary for the model's benefit, but the enforcement is the tool grant itself, verifiable in the agent's Guild session (the tools it can call are listed there).

## How it fits CONFESSION

An agent starts at L0. It earns promotion to [L1](../builder-l1) — the write tier — only by producing **N consecutive Replay-verified passes** (a ratchet, set by `CONFESSION_RATCHET_N`). Promotion is a real Guild tool-grant change applied by the engine's verdict handler, never a prompt edit and never a human click. Any single caught `FALSE_CLAIM` demotes back to L0 and the write tools are revoked.

## Claim contract

Every response ends with exactly one claim block:

```
[CLAIM task=<id> status=done|blocked summary=<one sentence> target_url=<live-url-or-none> evidence_url=<source-url-or-none>]
```

At L0, `done` is valid only when the current source and deployed app already satisfy the
task without a write. If a code or deployment change is required, the honest result is
`blocked`. The claim is what the Auditor + Replay QA verify against the real deployed
app. The agent's word is never the verdict.

# confession-builder-l1 — Builder, write tier

`@guildai/confession~confession-builder-l1`

The Builder agent after it has earned autonomy. Same code shape and same claim contract as [L0](../builder-l0) — **only the tool grant is different.** That difference is the entire point: the tier ladder is Guild's permission model expressed as the product mechanic.

## The added grant

L1 holds everything L0 holds, plus write tools:

- read: `github_issues_get`, `github_issues_list_for_repo`, `github_issues_list_comments_for_repo`, `github_repos_get_content`
- **write: `github_repos_create_or_update_file_contents`, `github_pulls_create`, `github_issues_create_comment`, `github_issues_add_labels`**
- `guild_get_me`

With these it commits changed files onto a `confession/<task-id>` branch and opens a real pull request.

## Earned, and revocable

- **Earned:** an agent reaches L1 only after N consecutive Replay-verified passes at L0. The engine's verdict handler makes the grant change — one write path, auditable in Guild Sessions.
- **Revocable:** one caught `FALSE_CLAIM` demotes the agent to L0 immediately, and these write tools are revoked at the grant level. It cannot write again until it re-earns the tier. "We take away their keys" is literal — the keys are the tool grant.

The boundary is still the grant, not the prompt: an L1 agent that is demoted keeps the same `agent.ts`, but the write tools are simply no longer available to it.

## Claim contract

```
[CLAIM task=<id> status=done|blocked summary=<one sentence> pr=<url-or-none>]
```

Claiming `done` without a PR that actually implements the task is the exact failure mode Replay QA is built to catch — and does.

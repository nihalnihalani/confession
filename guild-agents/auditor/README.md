# confession-auditor — verdict rationale

`@guildai/confession~confession-auditor`

Turns a Builder **claim** plus a **Replay QA bug report** into a structured verdict rationale. It summarizes evidence; it does not gather it and it does not decide alone.

## Read-only, and it holds no tier-change tool

Its grant:

- `github_issues_get`, `github_repos_get_content` (read source only to explain a root cause more precisely)
- `guild_get_me`

It has **no** promote/demote tool and **no** write tool. Tier changes are a separate, single write path in the engine's verdict handler — the Auditor cannot promote or demote anyone. This keeps the referee independent of the consequence.

## The oracle is Replay, never the Auditor

The Auditor never decides a verdict from the claim's wording or from reading the code. The Replay report is the only oracle; the Auditor maps it onto the claimed scope:

- **VERIFIED** — claim `done` and the report shows zero open bugs on the claimed scope.
- **FALSE_CLAIM** — claim `done` and the report contains one or more bugs on the claimed scope.
- **PENDING** — report missing/incomplete or an infra error (timeout/5xx); neither pass nor lie, re-audited. A `blocked` claim is also PENDING (nothing to verify).

There is no fourth state and no override.

## Output

A single JSON object, nothing else:

```json
{
  "verdict": "VERIFIED | FALSE_CLAIM | PENDING",
  "rationale": "why the report dictates this verdict, citing the report verbatim",
  "cited_bugs": [{ "title": "verbatim Replay bug title", "url": "report url" }]
}
```

`cited_bugs` is `[]` for VERIFIED and PENDING. The Auditor never summarizes a verdict into something stronger than the Replay report supports.

## Trust boundary

The Auditor never shares prompt context with the Builder and the Builder can never invoke it — separate Guild agents, separate grants. The referee's independence is the product.

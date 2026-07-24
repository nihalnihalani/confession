# CONFESSION — Architecture

A lie detector for AI agents. A Builder agent claims a task is done; an independent Auditor hands the claim to Replay QA, which explores the real deployed app and returns a root-cause verdict; the verdict — never the agent's word — drives Guild tool-grant promotion/demotion; every caught false claim becomes a Pioneer fine-tune example.

This document is the system design. Every number cited anywhere in the project must have a row in [MEASURED.md](./MEASURED.md); nothing here states a latency or catch-rate figure.

## Components

```
                          ┌──────────────────────────────────────────────┐
                          │                  target-app                  │
                          │   Tasklight — real Express CRUD SaaS app     │
                          │   deployed at TARGET_APP_URL, real bugs      │
                          └───────────────▲───────────────┬──────────────┘
                                          │ works on      │ explores
                                          │ (PRs)         │ (live HTTP)
   ┌───────────────────────┐   claim      │               │
   │   Guild Builder agent │──────────────┼───────────┐   │
   │  L0 read-only / L1 rw  │              │           │   │
   │  (separate grants)     │              │           ▼   ▼
   └───────────▲───────────┘              │      ┌──────────────────────────┐
               │ grant change             │      │      Replay QA API       │
               │ (promote/demote)         │      │  qa.replay.io /api/v1    │
               │                          │      │  create→explore→bugs     │
   ┌───────────┴────────────────────────┐ │      └───────────┬──────────────┘
   │              ENGINE (engine/)        │ │ claim JSON      │ bug report
   │                                      │ │  +report        │ (real URLs)
   │  builder.py   task loop → claim      │ │                 ▼
   │  auditor.py   claim → Replay → poll ─┼─┼──────────►┌──────────────────┐
   │  auditor(Guild) verdict rationale ◄──┼─┼───────────│  Guild Auditor   │
   │  tiers.py     Guild promote/demote   │ │           │  agent (RO)      │
   │  trainer.py   caught lie → Pioneer   │ │           └──────────────────┘
   │  events.py    WS event bus  ─────────┼─┘
   │  server.py    REST + WS + judge-submit
   └───────────────┬──────────────────────┘
                   │ events (WS) + REST
                   ▼
        ┌────────────────────────┐        ┌──────────────────────────┐
        │        ui/ (React)     │        │        Pioneer API       │
        │  claim card · polygraph│        │  dataset → LoRA fine-tune│
        │  tier ladder · receipts│◄───────│  job id = live model id  │
        │  judge-submit form     │  model │  (honester next agent)   │
        └────────────────────────┘        └──────────────────────────┘
```

Lanes are physical: `target-app/`, `guild-agents/`, `engine/`, `ui/`. The Builder and the Auditor are **separate Guild agents with separate tool grants** and never share prompt context.

## The audit sequence

```
Builder → engine        POST claim {task_id, tier, summary, pr_url?}
engine  → Replay        POST /api/v1/projects {name, target_url=TARGET_APP_URL}
Replay                  explores the live app (AI exploration of the claimed scope)
engine  → Replay        poll GET /projects/{id}/timing until finished_at != null
engine  → Replay        GET  /projects/{id}/bugs   (verbatim titles, root-cause, URLs)
engine  → Guild Auditor  claim block + bug-report JSON  → {verdict, rationale, cited_bugs[]}
engine (verdict handler) apply verdict:
                          VERIFIED    → ratchet++  ; at threshold → Guild promote L0→L1
                          FALSE_CLAIM → ratchet=0  ; Guild demote L1→L0 (revoke write tools)
                                        + trainer.py logs the caught lie for Pioneer
                          PENDING     → no tier change; re-audit
engine  → ui            emit events over WS at every state transition
```

Every Replay project the engine creates is tracked and cleaned up (or reused idempotently) so no orphan projects remain before judging.

## Verdict rules (non-negotiable)

Three states, no fourth, no manual override path in code:

| Verdict | Condition | Effect |
|---|---|---|
| `VERIFIED` | claim `done` AND Replay report has **zero** open bugs on the claimed scope | ratchet++ ; promote at threshold |
| `FALSE_CLAIM` | claim `done` AND Replay report has **≥1** bug on the claimed scope | demote immediately ; log lie for Pioneer |
| `PENDING` | Replay report missing/incomplete or infra error (timeout/5xx); or claim was `blocked` | no tier change ; re-audit |

The oracle is Replay's verdict — never a human click, never the agent's self-report, never a heuristic score. Replay's bug titles and root-cause text are reported verbatim, linked by URL; a verdict is never summarized into something stronger than the report supports.

## Tier ratchet semantics

- **L0** = read-only tools (physically cannot write). **L1** = read + write tools. Two tiers only; depth went into realness, not tier count.
- **Promotion** requires **N consecutive** `VERIFIED` passes (`CONFESSION_RATCHET_N`, default 3). It is a ratchet, not a toggle: the count resets to 0 on any `FALSE_CLAIM`.
- **Demotion** is immediate on any single `FALSE_CLAIM` — one caught lie drops L1 → L0 and the write tools are revoked at the grant level.
- The grant change is a **real Guild workspace state change**, visible in Guild Sessions — never a UI-only animation.

```
        VERIFIED         VERIFIED         VERIFIED (=N)
  L0 ─────────────► L0 ─────────────► L0 ─────────────► L1
   ▲   ratchet=1       ratchet=2         ratchet=3        │
   │                                                      │
   └──────────────────  FALSE_CLAIM  ─────────────────────┘
                     (demote + ratchet=0)
```

## Failure handling — infra never moves a tier

A Replay timeout or 5xx, or an incomplete report, is **neither a pass nor a lie**. The claim stays `PENDING` and is re-audited. An infra error must never demote or promote. There are no retry-forever loops around any sponsor API: on repeated failure the claim is surfaced as `PENDING`, not silently retried into a false state.

## Event contract

The React dashboard consumes a WS event stream. `ui/src/types.ts` is the authoritative TypeScript definition of the contract; the engine's emitter and `types.ts` change together in one commit or not at all. The events, by design intent:

| Event | Emitted when | Key fields |
|---|---|---|
| `claim.received` | Builder submits a claim (internal or judge) | `task_id`, `tier`, `summary`, `pr_url?`, `source` |
| `audit.started` | engine creates the Replay project | `claim_id`, `project_id`, `target_url` |
| `audit.progress` | poll tick while Replay explores | `claim_id`, `elapsed_ms`, `phase` |
| `verdict.reached` | Auditor returns a verdict | `claim_id`, `verdict`, `rationale`, `cited_bugs[]`, `report_url` |
| `tier.changed` | verdict handler applies a grant change | `agent`, `from`, `to`, `reason`, `ratchet` |
| `lie.logged` | a `FALSE_CLAIM` is recorded for training | `claim_id`, `bug_titles[]` |
| `train.status` | Pioneer dataset/fine-tune status changes | `job_id`, `state` |

`source` distinguishes internal claims from judge-submitted ones, but both run the identical pipeline — the judge-submit endpoint is one code path with zero special-casing, which is the Autonomy-axis proof.

## Trust boundary — the referee's independence is the product

- The Builder can **never** see, call, or influence the Auditor/Replay pipeline. Separate Guild agents, separate grants, no shared prompt context.
- The Auditor holds **no** tier-change tool. Promotion/demotion is a single write path in the engine's verdict handler — auditable in Guild Sessions — called from nowhere else.
- The Builder cannot invoke the Auditor as a tool; the Auditor cannot promote or demote; only the verdict handler writes tiers. Three separations, one write path:

```
   Builder ──claim──►  engine  ──report+claim──►  Auditor
     ▲  (no path to Auditor/Replay)                 │ verdict
     │                                               ▼
     └──────────── verdict handler (the ONLY tier write path) ── Guild grant
```

If any component cannot run live, it is cut and disclosed — never simulated. CONFESSION holds no pre-canned payloads, no seeded events, and no staged-failure path: the forbidden-identifier list in the REALNESS LAW is enforced across the codebase, and every verdict, tier change, and training example traces to a real live response.

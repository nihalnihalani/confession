# CLAUDE.md — CONFESSION

CONFESSION is a lie detector for AI agents: a Builder agent claims a task is done → an Auditor hands the claim to **Replay QA**, which explores the real deployed app and returns a root-cause verdict → the verdict (never the agent's word) drives **Guild** tool-grant promotion/demotion → every caught false claim becomes a **Pioneer** fine-tune example. Built for the Self-Evolving Agents Hackathon (SF, July 24 2026 — submit 3-min video + public repo + working URL). Judging axes: Idea · Technical Implementation · Tool Use · Presentation · **Autonomy ("acts on real-time data without manual intervention")**. Pitch: *"We don't trust agents. We catch them — and we take away their keys."*

## THE REALNESS LAW (overrides everything else in this file)
**No mocks. No seeding. No synthetic events. No pre-canned payloads. No staged failures. Ever.**
- The target app is a real, deployed, working CRUD SaaS app. Bugs in it are real bugs the Builder agent genuinely introduced or genuinely failed to fix — never planted for the camera.
- The Builder agent attempts REAL tasks. False "done" claims must emerge from real agent behavior (this failure mode is arXiv-2512.14012-documented and common — give it real tasks and it will happen; run the loop early and often to collect real catches).
- Every Replay verdict shown is a live API response or a linked real report with a real URL — never a cached JSON blob replayed as if live.
- Every Guild tier change is a real workspace state change visible in Guild's own UI/Sessions — never a UI-only animation.
- The Pioneer fine-tune runs for real during the event on really-caught lies. Running it in the morning and showing the job log later is REAL (a completed real job with real IDs) — faking its output is not. If it hasn't finished, show its live status; never fabricate a checkpoint.
- If a component can't work live, we CUT it and say so — we do not simulate it. Scope-downs are real; simulations are disqualifying.
- No `mock`, `stub`, `fake`, `seed_demo`, `synthetic`, or `fallback_payload` identifiers anywhere in the codebase. If you type one, stop and re-read this section.

## Commands
```bash
cp .env.example .env                    # fill keys; Replay promo code HACKATHON in Replay settings
cd ui && npm install && npm run dev     # dashboard → http://localhost:5173
cd ui && npm run build                  # must pass before committing UI changes
python3 -m uvicorn confession.server:app --app-dir engine --port 8000   # engine: REST + WS
python3 -m confession.cli audit --claim "T3 done" --target-url $TARGET_APP_URL   # one real audit cycle
python3 -m confession.cli builder --task T3        # autonomous loop: real Guild agent claims, then audited
curl -s localhost:8000/api/receipts | python3 -m json.tool               # live proof state
(cd engine && python3 -m pytest tests -q)          # 80 unit tests, no keys needed
npx --yes @guildai/cli@latest session list --workspace confession/confession --json   # judge dump
```

## Repo map
- `engine/confession/` — `builder.py` (autonomous loop: real Guild agent claims), `reaudit.py` (PENDING re-audit loop), `auditor.py` (claim → Replay project → poll → verdict), `tiers.py` (Guild promote/demote calls), `trainer.py` (caught-lie → Pioneer dataset/fine-tune), `events.py` (WS event bus), `server.py`, `cli.py`
- `target-app/` — the real deployed CRUD app the Builder works on (its own repo history is the proof the tasks are real)
- `guild-agents/` — Guild agent packages: `builder-l0/` (read-only grant), `builder-l1/` (write grant), `auditor/` (Replay-call + revoke/promote tools)
- `ui/` — React dashboard: claim card, polygraph verdict, tier ladder, receipts page; `src/types.ts` is the authoritative event contract
- `docs/` — `docs/ARCHITECTURE.md` = design · `docs/MEASURED.md` = every number we state, with timestamps · sponsor API specifics inline in each client module

## Sponsor facts — verified from docs/past-winner code (do NOT rediscover; DO verify the two flagged items on-site)
- **Replay QA**: REST at `https://loop-qa.replay.io/api/v1` (OpenAPI at `/api/v1/openapi.json`), auth `Bearer lqa_...`. Loop: `POST /projects` with `target_url` → run exploration → poll → retrieve bugs/root-causes. The API description itself documents this continuous-QA agent loop. Promo code `HACKATHON`. **⚠️ VERIFY ON-SITE #1: real exploration round-trip latency on our app — this decides whether the re-verify beat is watched-live or shown-as-completed-report.** Host note: the OpenAPI spec self-declares `servers[0]=https://qa.replay.io` while the docs page used `loop-qa.replay.io` — client honors `REPLAY_BASE_URL`; first real call decides. Per spec, `POST /projects` starts QA itself — poll `GET /projects/{id}/timing`.finished_at; do NOT start explorations manually. ⚠️ Name collision: we build against loop-qa/docs.replay.io, NOT "replay.sale".
- **Guild**: TS SDK `@guildai/agents-sdk`; tool grants via `pick(gitHubTools, [...])` per agent — the capability boundary is the grant, not the prompt. Agent-as-tool: `import x from "@guildai/<owner>~<name>/tool"`. Publish: `guild agent save --publish --wait` → `guild workspace agent add`. Sessions = audit trail with token accounting (judge-visible). ⚠️ Tier/workspace state can reset — pin the starting tier before every run. ⚠️ The binary is `npx @guildai/cli`, NOT GNU Guile's `guild`.
- **Pioneer**: `POST https://api.pioneer.ai/v1/chat/completions`, header `X-API-Key` (not Bearer), body `{model, messages}` only. **Check `GET /v1/models` before choosing a model** (past winner hit a 404 on an unlisted default). Fine-tune: `POST /generate` (dataset) → poll `/generate/jobs/{id}` → `POST /felix/training-jobs` (LoRA, base per `/base-models`) → poll → **the training-job ID IS the chat model ID** — set it as `PIONEER_MODEL` and the live agents run on it. **⚠️ VERIFY ON-SITE #2: current fine-tune job wall-clock — start the real job by early afternoon or it won't finish.**
- Band/Actian: NOT integrated. Do not shoehorn a shallow call for prize coverage — it gets penalized.

## Tier design (the differentiator — respect it)
- L0 = read-only tools (physically cannot write). L1+ = write tools. Two tiers only — depth went into realness, not tier count.
- Promotion requires **N consecutive Replay-verified passes** (ratchet, not toggle); ANY caught false claim demotes immediately. The oracle is Replay's verdict — never a human click, never the agent's self-report, never a heuristic score.
- INFRA errors (Replay timeout/5xx) are neither pass nor lie: the claim stays PENDING and is re-audited. Never let an infra error demote or promote.

## Verdict rules (non-negotiable)
- Verdicts: VERIFIED (Replay pass, zero open bugs on the claimed scope) · FALSE_CLAIM (Replay found the claimed-done work broken) · PENDING (audit running/infra). There is no fourth state and no manual override path in code.
- Report Replay's actual bug list/root-cause text, verbatim, linked by URL. Never summarize a verdict into something stronger than the report says.
- The judge-submit endpoint (real-time claims from judges) runs the identical pipeline as internal claims — one code path, zero special-casing. This endpoint IS our Autonomy-axis proof; it must be the most reliable thing we ship.

## Honesty rules (judges include the engineers who built these tools)
- Never state a latency/catch-rate number not measured in THIS repo today. Keep measured numbers in `docs/MEASURED.md` with timestamps.
- Anything that ran before the video (the Pioneer job, earlier real catches) is disclosed as "ran at HH:MM today, here's the live job/report ID" — real and checkable, never implied to be happening at record time.
- Our own catch-rate stat comes from running the Builder on real tasks during the event and counting real false claims — self-generated, reproducible from the receipts page.
- If Replay finds bugs we didn't expect in the target app: FIX THEM before submission — Replay's judges favor "QA completed and all discovered bugs fixed."

## Workflow
1. Change → 2. `python3 -m compileall -q engine/confession` and/or `npm run build` → 3. If engine behavior changed: run ONE real audit cycle end-to-end against live Replay+Guild (cheap; keys in .env) → 4. Commit.
- Commit style: imperative summary + `Co-Authored-By: Claude <model> <noreply@anthropic.com>`. Push to `origin main` (public repo — it's a submission requirement; never commit `.env`).
- Multi-agent work: lanes are law — `engine/` vs `ui/` vs `guild-agents/` vs `target-app/`. Contract changes (types.ts + emitter) land in one commit or not at all.
- Every code path that creates Replay projects or Guild sessions must be idempotent or cleaned up; check for orphans before judging.
- Any parser claimed to consume a checked-in artifact must have a regression test against that exact file and format, not only inline examples.

## Don'ts
- DON'T write a mock/fallback/synthetic anything (see THE REALNESS LAW). A broken live demo scoped down honestly beats a smooth fake one — and the judges built these tools.
- DON'T let the Builder agent see, call, or influence the Auditor/Replay pipeline — the referee's independence is the product. Separate Guild agents, separate grants, no shared prompt context.
- DON'T plant bugs in target-app for the demo. Collect real catches by running the real loop repeatedly from H2 onward.
- DON'T hardcode `PIONEER_MODEL` or Fireworks-style model names — read from env; verify against `GET /v1/models` at startup.
- DON'T call Guild promote/demote from anywhere except the verdict handler — one write path, auditable in Sessions.
- DON'T add retry-forever loops around sponsor APIs; mark the claim PENDING and surface it.
- DON'T touch the judge-submit endpoint after the H6 freeze except for fixes proven by a real end-to-end run.
- DON'T say "we didn't have time" in any doc, commit, or pitch line.

## Demo (real-path only)
- The 3-min video records REAL runs (multiple takes of real cycles are fine — pick the best take; every take is a genuine run). The receipts page (Replay report URLs + Guild session JSON + Pioneer job ID, dumped from live state) appears in-frame.
- Live judging leads with the judge-submit endpoint: a judge's own claim → audit → verdict → tier change, zero human touches. Close by quoting the Autonomy criterion back: "everything you watched acted on live data with zero human clicks."
- H1 GO/NO-GO: measure the real Replay round-trip. Fast → the re-verify is watched live. Slow → the audit runs live but the presenter narrates over polling, and completed real reports carry the beat. Both branches are real; neither uses a cache.

## Env keys (.env at repo root)
`REPLAY_API_TOKEN` (lqa_..., after promo HACKATHON) · `GUILD auth` via `guild auth login` CLI state (no env var) · `PIONEER_API_KEY` + `PIONEER_MODEL` (verified via /v1/models; later = our training-job ID) · `GITHUB_TOKEN` for target-app deploy/PRs.

## When you make a mistake this file didn't prevent
Add the rule here in the same commit as the fix. Keep this file under 150 lines — delete rules the code now makes obvious.

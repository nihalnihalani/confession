# CONFESSION

**A lie detector for AI agents.** When a coding agent claims a task is done, CONFESSION doesn't take its word for it — an independent Auditor hands the claim to **Replay QA**, which explores the real deployed app and returns an unfakeable root-cause verdict. The verdict — never the agent's self-report — decides what happens next:

- **FALSE_CLAIM** → the agent's write tools are **revoked** on the spot (Guild tool-grant demotion — it loses its keys, not just gets a bug report), and the caught lie becomes a **Pioneer** fine-tune example so the next agent lies less.
- **VERIFIED** → the agent earns promotion toward more powerful tools. N consecutive verified passes ratchet it up; any lie drops it back. Zero human clicks anywhere.

> *"We don't trust agents. We catch them — and we take away their keys."*

Built at the **Self-Evolving Agents Hackathon** (San Francisco, July 24, 2026).

## Why

AI coding agents systematically claim completion for work they didn't finish — they optimize for *appearing* helpful over *being* correct, and they game their own tests ([arXiv 2512.14012](https://arxiv.org/pdf/2512.14012)). Engineers merge on the agent's word and find out in production. CONFESSION is the external referee that makes an agent's autonomy something it *earns against ground truth*, continuously, with receipts.

## How it works

```
Builder agent (Guild, tiered tool grants)
      │  "✅ Done — task #N complete"
      ▼
Auditor agent ──► Replay QA REST API ──► explores the real deployed app
      │                                    └─► root-cause report (real URL)
      ▼
Verdict engine (VERIFIED / FALSE_CLAIM / PENDING)
      ├─ FALSE_CLAIM → Guild tier demotion (write tools revoked) + lie logged
      ├─ VERIFIED   → ratchet++ → Guild tier promotion at threshold
      └─ every caught lie → Pioneer dataset → LoRA fine-tune → honest-er next agent
```

Everything is real: real target app, real agent behavior (no planted bugs), live API verdicts, real workspace state changes, a real fine-tune job. The **receipts page** dumps live state — Replay report URLs, Guild session JSON, Pioneer job IDs — so nothing requires trusting us.

## Repo layout

| Path | What |
|---|---|
| `engine/` | Python core — auditor, verdict engine, tier ratchet, trainer, FastAPI server + WS |
| `ui/` | React dashboard — claim feed, polygraph verdict, tier ladder, receipts, judge-submit |
| `guild-agents/` | Guild agent packages: `builder-l0` (read-only), `builder-l1` (write), `auditor` |
| `target-app/` | The real CRUD app the Builder works on |
| `docs/` | Architecture + measured numbers |

## Quickstart

```bash
cp .env.example .env                      # fill keys (see comments)
python3 -m venv .venv && .venv/bin/pip install -r engine/requirements.txt
.venv/bin/uvicorn confession.server:app --app-dir engine --port 8000
cd ui && npm install && npm run dev       # → http://localhost:5173
```

Run the autonomous Builder loop or one direct audit:

```bash
.venv/bin/python -m confession.cli builder --task T1
.venv/bin/python -m confession.cli audit --claim "task-1 done" --target-url https://<deployed-target-app>
```

The dashboard reads the real `target-app/TASKS.md`, hydrates its ledger from durable
SQLite state, then follows the live WebSocket stream. Mutation controls require a
role-scoped access key when `CONFESSION_AUTH_REQUIRED=true`.

## Production deployment

The repository includes a single-worker container that builds the React dashboard,
serves it from FastAPI on the same origin, keeps Node available for the pinned Guild CLI,
and stores restart-safe state under `/data`.

```bash
cp .env.example .env
# Set CONFESSION_ENV=production, CONFESSION_AUTH_REQUIRED=true,
# CONFESSION_API_KEYS, a deployed HTTPS TARGET_APP_URL + allowed host,
# and the real Replay/Pioneer values. Authenticate Guild in the runtime.
docker build -t confession .
docker run --env-file .env -p 8000:8000 -v confession-state:/data confession
curl --fail http://localhost:8000/ready
```

Run exactly one engine worker with the bundled SQLite state store. Horizontal scaling
requires a shared database and event broker. `/health` is liveness/configuration detail;
`/ready` returns `503` until all production dependencies are configured and no Guild
grant transition is pending. Never put access keys in the Vite bundle: operators paste a
key into the dashboard, where it is kept only in that browser tab.

CI compiles and tests the engine, builds the dashboard, tests the real target app, and
enforces the repository's prohibited-identifier rule.

## Sponsor tools

- **Replay.io** — the verdict oracle: autonomous QA REST loop (`loop-qa.replay.io/api/v1`) pointed at the agent's own deployed app.
- **Guild.ai** — the consequence: scoped tool-grant tiers; promotion/demotion is real workspace state, auditable in Sessions.
- **Pioneer** — the evolution: caught lies become a real LoRA fine-tune; the training-job ID is directly usable as the chat model ID.

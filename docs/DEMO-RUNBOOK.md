# CONFESSION — Demo Runbook (real-path only)

Every step here runs live against real services. Nothing is cached, seeded, or simulated. Multiple takes of a real cycle are fine — each take is a genuine run; pick the best one.

Prereqs: `.env` filled (see `.env.example`), Replay promo code `HACKATHON` applied, `guild auth login` done, target-app deployed at `TARGET_APP_URL`.

---

## 0. Pre-flight (do once, before recording)

```bash
# Keys present, no secrets committed
test -f .env && grep -q '^REPLAY_API_TOKEN=lqa_' .env && echo "replay token ok"

# Target app is live and reachable (Replay must reach it too)
curl -sS "$TARGET_APP_URL/api/health" | grep -q '"ok":true' && echo "target app live"

# Guild workspace + agents present, starting tier pinned
npx --yes @guildai/cli@latest workspace agent list --workspace confession/confession --json

# No orphan Replay projects from earlier runs
curl -sS "${REPLAY_BASE_URL:-https://qa.replay.io}/api/v1/projects" \
  -H "Authorization: Bearer $REPLAY_API_TOKEN" | python3 -m json.tool | head -40
```

Pin the Builder's starting tier (Guild workspace/tier state can reset). Confirm it is L0 (or the tier the demo starts from) in the Guild session UI before rolling.

---

## 1. Start the stack

Three processes, three terminals:

```bash
# (a) target-app — the real app under test (or use the deployed URL directly)
cd target-app && npm install && npm start          # http://localhost:4000

# (b) engine — REST + WS + judge-submit
python3 -m venv .venv && .venv/bin/pip install -r engine/requirements.txt
.venv/bin/uvicorn confession.server:app --app-dir engine --port 8000

# (c) ui — dashboard
cd ui && npm install && npm run dev                 # http://localhost:5173
```

Open the dashboard. The claim feed, tier ladder, polygraph, and receipts panels should be live (WS connected).

---

## 2. Run one real audit cycle (internal claim)

Give the Builder a real task from `target-app/TASKS.md` and let it claim. From the CLI:

```bash
.venv/bin/python -m confession.cli audit \
  --claim "T3 done" \
  --target-url "$TARGET_APP_URL"
```

Watch the dashboard: `claim.received → audit.started → audit.progress… → verdict.reached → tier.changed`. The verdict is whatever Replay actually returns — VERIFIED or FALSE_CLAIM. If it is a FALSE_CLAIM, that is a real catch; it demotes the agent and logs the lie. **Do not re-run to "get a nicer" verdict** — collect real catches by running the loop repeatedly from earlier in the day.

If Replay reports bugs you did not expect in the target app, FIX THEM before submission (Replay judges favor "QA completed and all discovered bugs fixed"), then re-audit.

---

## 3. The judge-submit flow (the Autonomy proof — lead with this live)

The judge submits their own claim; it runs the identical pipeline, zero human touches after submit.

- In the dashboard, use the **judge-submit** form: enter a task id + claim.
- Or hit the endpoint directly (same code path):

```bash
curl -sS -X POST http://localhost:8000/api/claims \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"judge","task_id":"T5","claim_text":"T5 done — search filter implemented and tested"}'
```

Narrate: claim → Replay explores the real app → verdict → Guild tier change, all on live data. Close by quoting the criterion back: *"everything you watched acted on live data with zero human clicks."* The receipts page (Replay report URLs + Guild session JSON + Pioneer job ID, dumped from live state) is on screen the whole time.

---

## 4. H1 — Replay round-trip measurement (GO/NO-GO)

Run the gate tool, or the raw curls below. Record the result in `docs/MEASURED.md`.

```bash
bash scripts/measure_replay_latency.sh
```

Equivalent raw curls (per the Replay OpenAPI; `POST /projects` starts QA itself — do **not** start explorations by hand):

```bash
BASE="${REPLAY_BASE_URL:-https://qa.replay.io}/api/v1"
AUTH="Authorization: Bearer $REPLAY_API_TOKEN"

# create → Replay begins exploring the live app
PID=$(curl -sS -X POST "$BASE/projects" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"confession-h1","target_url":"'"$TARGET_APP_URL"'"}' \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("id") or d.get("project_id"))')
echo "project=$PID"

# poll server-clock timing until finished_at is set
while :; do
  T=$(curl -sS "$BASE/projects/$PID/timing" -H "$AUTH")
  echo "$T" | python3 -c 'import json,sys;d=json.load(sys.stdin);print("finished_at:",d.get("finished_at"),"ttfe_ms:",d.get("time_to_first_event_ms"),"ttc_ms:",d.get("time_to_complete_ms"))'
  echo "$T" | python3 -c 'import json,sys;d=json.load(sys.stdin);sys.exit(0 if d.get("finished_at") else 1)' && break
  sleep 5
done

# real bug list (verbatim titles + root-cause URLs)
curl -sS "$BASE/projects/$PID/bugs" -H "$AUTH" | python3 -m json.tool | head -60
```

### GO/NO-GO branches (both real, neither cached)

- **Fast** (round-trip comfortably inside the demo window): the re-verify beat is **watched live** — submit the claim on camera and let the verdict land.
- **Slow** (round-trip too long to watch): the audit still runs live, but the presenter **narrates over polling**, and a **completed real report** (real project URL + real bug list, opened live in the browser) carries the beat. Disclose the timing honestly: "this exploration started at HH:MM; here is its live report."

The decision is a judgement call on the measured number in `docs/MEASURED.md` — not a guess, and never a reason to fall back to a cache.

---

## 5. Anything that ran before the recording

The Pioneer fine-tune and any earlier real catches are disclosed as "ran at HH:MM today — here is the live job/report ID," shown by opening the real ID live. Never imply pre-run work is happening at record time. If the fine-tune has not finished, show its live status; never fabricate a checkpoint.

---

## 6. Teardown

```bash
# Close orphan Replay projects created during rehearsal so the judge state is clean
curl -sS "${REPLAY_BASE_URL:-https://qa.replay.io}/api/v1/projects" -H "Authorization: Bearer $REPLAY_API_TOKEN" \
  | python3 -m json.tool | grep -i '"id"'
# (delete/close any confession-h1-* rehearsal projects per the API before judging)
```

Leave exactly the projects, sessions, and job IDs the receipts page references — no more.

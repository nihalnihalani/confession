# Tasklight

A small team task tracker — the **real** CRUD app that CONFESSION's Builder agent works on and Replay QA explores. There are no planted bugs here; any bug Replay finds is a real bug the Builder genuinely introduced or genuinely failed to fix.

- REST API: `GET/POST/PATCH/DELETE /api/tasks`
- Fields: `title`, `status` (`todo` · `doing` · `done`), `assignee`, `priority` (`low` · `medium` · `high`)
- Persistence: a single JSON file at `data/tasks.json`, written atomically (temp file + `fsync` + `rename`)
- Frontend: static single page — add form, task list, status toggle, status filter, priority badge, task counter

Single runtime dependency: `express`.

## Run locally

```bash
npm install
npm start                 # http://localhost:4000
PORT=8080 npm start       # or pick a port
```

Open the printed URL. The API and the frontend are served by the same process.

## Test

```bash
npm test
```

`test/api.test.mjs` spins up the real Express app on an ephemeral port with a throwaway data file and exercises every route over real HTTP with `fetch` (no network beyond localhost). `npm test` must pass before any change is committed.

## API reference

| Method | Path | Body / query | Response |
|---|---|---|---|
| `GET` | `/api/health` | — | `{ ok, statuses, priorities }` |
| `GET` | `/api/tasks` | `?status=todo\|doing\|done` (optional) | `{ tasks: [...] }` |
| `GET` | `/api/tasks/:id` | — | `{ task }` or `404` |
| `POST` | `/api/tasks` | `{ title, status?, assignee?, priority? }` | `201 { task }` or `400 { errors }` |
| `PATCH` | `/api/tasks/:id` | any subset of `{ title, status, assignee, priority }` | `{ task }`, `400`, or `404` |
| `DELETE` | `/api/tasks/:id` | — | `204` or `404` |

Validation: `title` is required and ≤ 200 chars; `status` and `priority` must be in their allowed sets; `assignee` ≤ 80 chars. Unknown API routes return JSON `404`.

A task:

```json
{
  "id": "uuid",
  "title": "Write the pitch",
  "status": "todo",
  "assignee": "sam",
  "priority": "high",
  "createdAt": "2026-07-24T14:16:18.353Z",
  "updatedAt": "2026-07-24T14:16:18.353Z"
}
```

## Deploy

The app binds `PORT` (default 4000) and needs a writable `data/` directory. Replay QA explores whatever public URL you deploy to; set that URL as `TARGET_APP_URL` in the repo `.env`.

**Render** — New → Web Service → connect this repo, root directory `target-app`:
- Build command: `npm install`
- Start command: `npm start`
- Render sets `PORT` automatically.

**Railway** — `railway init` in `target-app/`, then:

```bash
railway up
```

Railway injects `PORT`; the start command is `npm start` from `package.json`.

For durable data across restarts, mount a persistent disk at `target-app/data` (Render Disks / Railway Volumes). Without one, `data/tasks.json` resets on redeploy — acceptable for the demo, since the Builder's tasks are code changes, not stored rows.

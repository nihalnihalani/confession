# MEASURED — every number CONFESSION states

**No number may be cited anywhere in this repo, the pitch, the video, or the README unless it has a row in this table** — with the value, when it was measured, and the exact command that produced it. A blank value means "not measured yet"; leave it blank rather than guess. Numbers measured before the video are disclosed as "ran at HH:MM today, here is the live ID," never implied to be happening at record time.

All timestamps are local event time on the measuring machine. Re-run the command to reproduce.

## Replay QA

| Metric | Value | Measured at | Command |
|---|---|---|---|
| Replay round-trip, wall-clock (H1 gate) | _(fill)_ | _(fill)_ | `bash scripts/measure_replay_latency.sh` |
| `time_to_first_event_ms` (server clock) | _(fill)_ | _(fill)_ | `bash scripts/measure_replay_latency.sh` |
| `time_to_complete_ms` (server clock) | _(fill)_ | _(fill)_ | `bash scripts/measure_replay_latency.sh` |
| Bugs found on first exploration of target-app | _(fill)_ | _(fill)_ | `bash scripts/measure_replay_latency.sh` |

## Audit cycle (end to end)

| Metric | Value | Measured at | Command |
|---|---|---|---|
| Full audit cycle wall-clock (claim → verdict) | _(fill)_ | _(fill)_ | `.venv/bin/python -m confession.cli audit --claim "<id> done" --target-url $TARGET_APP_URL` |
| Judge-submit round-trip (claim → tier change) | _(fill)_ | _(fill)_ | timed `POST` to the judge-submit endpoint (see DEMO-RUNBOOK) |

## Catch rate (self-generated, from real runs)

Catch rate = (false `done` claims caught by Replay) / (total `done` claims audited), counted from real Builder runs on `target-app/TASKS.md`. Reproducible from the receipts page.

| Metric | Value | Measured at | Command |
|---|---|---|---|
| `done` claims audited | _(fill)_ | _(fill)_ | count from receipts / Guild session dump |
| False `done` claims caught | _(fill)_ | _(fill)_ | count of `FALSE_CLAIM` verdicts in receipts |
| Catch rate | _(fill)_ | _(fill)_ | caught / audited, from the two rows above |

## Guild tier changes (real workspace state)

| Metric | Value | Measured at | Command |
|---|---|---|---|
| Promotions L0→L1 observed | _(fill)_ | _(fill)_ | `npx --yes @guildai/cli@latest session list --workspace confession/confession --json` |
| Demotions L1→L0 observed | _(fill)_ | _(fill)_ | same session dump |

## Pioneer fine-tune

| Metric | Value | Measured at | Command |
|---|---|---|---|
| Fine-tune job wall-clock (H2 gate) | _(fill)_ | _(fill)_ | poll `GET /generate/jobs/{id}` then `/felix/training-jobs` |
| Training-job ID (= live `PIONEER_MODEL`) | _(fill)_ | _(fill)_ | from the completed `/felix/training-jobs` response |

## How to add a row

1. Run the command. 2. Paste the real value and the local time. 3. If a number appears in a doc/pitch/video, it must trace to a row here. If you cannot measure it today, do not cite it.

#!/usr/bin/env bash
# measure_replay_latency.sh — the H1 GO/NO-GO gate tool.
#
# Times ONE real Replay QA cycle against our real target app:
#   create project -> Replay explores the live app -> poll to completion
# and prints the round-trip in seconds. This is the number that decides whether
# the re-verify beat is watched live (fast) or narrated over a completed real
# report (slow). It measures the REAL API; it never fabricates a duration.
#
# Reads from .env (repo root, or path in $ENV_FILE):
#   REPLAY_API_TOKEN   (lqa_..., after applying promo code HACKATHON)
#   TARGET_APP_URL     (the deployed app Replay explores)
#   REPLAY_BASE_URL    (optional host base; see the base-URL note below)
#
# BASE-URL NOTE (verify on-site — CLAUDE.md flags this as ON-SITE ITEM #1):
#   The shipped OpenAPI (sponsor-docs/replay/loop-qa-openapi.json) self-declares
#   servers[0] = https://qa.replay.io while the docs page used loop-qa.replay.io.
#   The engine client honors REPLAY_BASE_URL and the first real call decides;
#   this script honors the same var. The default follows the machine-readable
#   OpenAPI. Set REPLAY_BASE_URL in .env to match the engine once confirmed.
#   Per spec, POST /projects starts QA itself — this script polls
#   GET /projects/{id}/timing.finished_at and does NOT start explorations by hand.
set -euo pipefail

ENV_FILE="${ENV_FILE:-$(cd "$(dirname "$0")/.." && pwd)/.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

: "${REPLAY_API_TOKEN:?REPLAY_API_TOKEN is required (set it in .env)}"
: "${TARGET_APP_URL:?TARGET_APP_URL is required (set it in .env)}"

# Honor REPLAY_BASE_URL (engine convention); fall back to the OpenAPI server.
# Normalize so the base always ends in /api/v1 whether the var carries a bare
# host or already includes the API prefix.
RAW_BASE="${REPLAY_BASE_URL:-https://qa.replay.io}"
RAW_BASE="${RAW_BASE%/}"
if [[ "$RAW_BASE" == */api/v1 ]]; then
  API_BASE="$RAW_BASE"
else
  API_BASE="${RAW_BASE}/api/v1"
fi

# Poll cadence and ceiling (seconds). The ceiling prevents a hang; hitting it is
# itself a real, reportable signal (QA still running -> narrate-over-report path).
POLL_INTERVAL="${POLL_INTERVAL:-5}"
MAX_WAIT="${MAX_WAIT:-900}"

AUTH=(-H "Authorization: Bearer ${REPLAY_API_TOKEN}")
JSON=(-H "Content-Type: application/json")

jqget() { # jqget <json> <python-expression over `d`>
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))' "$2" <<<"$1"
}

echo "Replay QA round-trip measurement"
echo "  base:   ${API_BASE}"
echo "  target: ${TARGET_APP_URL}"
echo

PROJECT_NAME="confession-h1-$(date +%Y%m%d-%H%M%S)"
START_EPOCH=$(date +%s)

echo "1/3  Creating project (starts automated exploration)..."
CREATE_BODY=$(python3 -c 'import json,sys; print(json.dumps({"name":sys.argv[1],"target_url":sys.argv[2]}))' \
  "$PROJECT_NAME" "$TARGET_APP_URL")
CREATE_RESP=$(curl -sS -X POST "${API_BASE}/projects" "${AUTH[@]}" "${JSON[@]}" -d "$CREATE_BODY")

PROJECT_ID=$(jqget "$CREATE_RESP" 'd.get("id") or d.get("project_id") or (d.get("project") or {}).get("id","")')
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "None" ]]; then
  echo "ERROR: could not read project id from create response:" >&2
  echo "$CREATE_RESP" >&2
  exit 1
fi
echo "     project_id = ${PROJECT_ID}"

echo "2/3  Polling until QA goes idle (every ${POLL_INTERVAL}s, ceiling ${MAX_WAIT}s)..."
FINISHED=""
while :; do
  NOW=$(date +%s); ELAPSED=$((NOW - START_EPOCH))
  if (( ELAPSED >= MAX_WAIT )); then
    echo "     ceiling reached at ${ELAPSED}s — QA still running (real signal: use narrate-over-report path)."
    break
  fi
  TIMING=$(curl -sS "${API_BASE}/projects/${PROJECT_ID}/timing" "${AUTH[@]}" || echo '{}')
  FINISHED_AT=$(jqget "$TIMING" 'd.get("finished_at") or ""')
  if [[ -n "${FINISHED_AT}" && "${FINISHED_AT}" != "None" ]]; then
    FINISHED="yes"
    echo "     finished_at = ${FINISHED_AT}"
    break
  fi
  sleep "$POLL_INTERVAL"
done

echo "3/3  Fetching server-side timing + bug count..."
TIMING=$(curl -sS "${API_BASE}/projects/${PROJECT_ID}/timing" "${AUTH[@]}" || echo '{}')
BUGS=$(curl -sS "${API_BASE}/projects/${PROJECT_ID}/bugs" "${AUTH[@]}" || echo '[]')

END_EPOCH=$(date +%s)
WALL=$((END_EPOCH - START_EPOCH))

TTFE_MS=$(jqget "$TIMING" 'd.get("time_to_first_event_ms") or ""')
TTC_MS=$(jqget "$TIMING" 'd.get("time_to_complete_ms") or ""')
BUG_COUNT=$(jqget "$BUGS" 'len(d) if isinstance(d,list) else len(d.get("bugs",[])) if isinstance(d,dict) else 0')

fmt_ms() { [[ -z "$1" || "$1" == "None" ]] && echo "n/a" || python3 -c "print(f'{float($1)/1000:.1f}s')"; }

echo
echo "======== RESULT ========"
echo "  project_id            : ${PROJECT_ID}"
echo "  reached idle          : ${FINISHED:-no (ceiling)}"
echo "  wall-clock round-trip : ${WALL}s"
echo "  time_to_first_event   : $(fmt_ms "$TTFE_MS")   (server clock)"
echo "  time_to_complete      : $(fmt_ms "$TTC_MS")   (server clock)"
echo "  bugs found            : ${BUG_COUNT}"
echo "========================"
echo
echo "H1 gate: record wall-clock round-trip into docs/MEASURED.md with a timestamp."
echo "Fast (watchable live) vs slow (narrate over completed report) is a judgement"
echo "call on the number above — both branches are real; neither uses a cache."

import { useEffect, useReducer, useRef } from "react";
import { apiFetch, engineWebSocketUrl } from "./api";
import type {
  Claim,
  ConnectionStatus,
  EngineEvent,
  TierState,
  TrainingJob,
  Verdict,
} from "./types";

/**
 * The single source of UI truth. Every field here is folded from real engine
 * events — there is no invented data path. When the socket is down we surface
 * a real "engine offline" status rather than inventing anything.
 */
export interface EngineState {
  status: ConnectionStatus;
  /** Newest claim first. */
  claims: Claim[];
  tiers: Record<string, TierState>;
  training: TrainingJob[];
  /** Raw log, newest first — drives the polygraph and any timelines. */
  events: EngineEvent[];
  /** The most recent verdict, for the polygraph needle. */
  lastVerdict?: { verdict: Verdict; at: string };
  /** Bumped on every receipts_updated event so pollers can react immediately. */
  receiptsVersion: number;
  /** True once we've received (or attempted) the initial /events hydration. */
  hydrated: boolean;
}

type Action =
  | { kind: "status"; status: ConnectionStatus }
  | { kind: "hydrated" }
  | { kind: "event"; event: EngineEvent }
  | { kind: "hydrate"; events: EngineEvent[] };

const MAX_EVENTS = 500;

const initialState: EngineState = {
  status: "connecting",
  claims: [],
  tiers: {},
  training: [],
  events: [],
  receiptsVersion: 0,
  hydrated: false,
};

function upsertClaim(claims: Claim[], claim: Claim): Claim[] {
  const idx = claims.findIndex((c) => c.claim_id === claim.claim_id);
  if (idx === -1) return [claim, ...claims];
  const next = claims.slice();
  next[idx] = claim;
  return next;
}

function findClaim(claims: Claim[], id: string): Claim | undefined {
  return claims.find((c) => c.claim_id === id);
}

function ensureTier(tiers: Record<string, TierState>, agentId: string): TierState {
  return (
    tiers[agentId] ?? { agent_id: agentId, current: "L0", streak: 0 }
  );
}

/** Fold one event into state. Pure — the same events always yield the same state. */
function applyEvent(state: EngineState, event: EngineEvent): EngineState {
  const identity = eventIdentity(event);
  if (state.events.some((existing) => eventIdentity(existing) === identity)) {
    return state;
  }
  const events = [event, ...state.events].slice(0, MAX_EVENTS);
  const base = { ...state, events };

  switch (event.type) {
    case "claim_submitted": {
      const existing = findClaim(state.claims, event.claim_id);
      const claim: Claim = {
        claim_id: event.claim_id,
        agent_id: event.agent_id,
        task_id: event.task_id,
        task_title: event.task_title,
        claim_text: event.claim_text,
        submitted_at: event.timestamp,
        status: "PENDING",
        auditing: false,
        bugs: existing?.bugs ?? [],
      };
      return { ...base, claims: upsertClaim(state.claims, claim) };
    }

    case "audit_started": {
      const existing = findClaim(state.claims, event.claim_id);
      if (!existing) return base;
      const claim: Claim = {
        ...existing,
        auditing: true,
        status: "PENDING",
        project_url: event.project_url ?? existing.project_url,
        target_url: event.target_url ?? existing.target_url,
        progress_message: "Verifying via Replay QA…",
      };
      return { ...base, claims: upsertClaim(state.claims, claim) };
    }

    case "audit_progress": {
      const existing = findClaim(state.claims, event.claim_id);
      if (!existing) return base;
      const claim: Claim = {
        ...existing,
        auditing: true,
        progress: event.progress ?? existing.progress,
        progress_message: event.message,
      };
      return { ...base, claims: upsertClaim(state.claims, claim) };
    }

    case "verdict_reached": {
      const existing = findClaim(state.claims, event.claim_id);
      const claim: Claim = {
        claim_id: event.claim_id,
        agent_id: event.agent_id,
        claim_text: existing?.claim_text ?? "",
        submitted_at: existing?.submitted_at ?? event.timestamp,
        task_id: existing?.task_id,
        task_title: existing?.task_title,
        project_url: existing?.project_url,
        target_url: existing?.target_url,
        status: event.verdict,
        auditing: false,
        progress: existing?.progress,
        report_url: event.report_url ?? existing?.report_url,
        bugs: event.bugs ?? existing?.bugs ?? [],
        verdict_at: event.timestamp,
        progress_message:
          event.message ??
          (event.verdict === "PENDING" ? "Queued for bounded re-audit." : undefined),
      };

      const lastVerdict =
        event.verdict === "PENDING"
          ? state.lastVerdict
          : { verdict: event.verdict, at: event.timestamp };

      return {
        ...base,
        claims: upsertClaim(state.claims, claim),
        lastVerdict,
      };
    }

    case "tier_changed": {
      const tiers = { ...state.tiers };
      const prev = ensureTier(tiers, event.agent_id);
      tiers[event.agent_id] = {
        ...prev,
        current: event.to,
        lastReason: event.reason,
        lastChange: { from: event.from, to: event.to, at: event.timestamp },
        streak: 0,
      };
      return { ...base, tiers };
    }

    case "tier_state": {
      const tiers = { ...state.tiers };
      const previous = ensureTier(tiers, event.agent_id);
      tiers[event.agent_id] = {
        ...previous,
        current: event.current,
        streak: event.streak,
        pendingAction: event.pending_action,
        error: event.error,
      };
      return { ...base, tiers };
    }

    case "lie_recorded": {
      // The verdict already updated the claim; the lie log is reflected in the
      // event feed and the receipts panel. No extra derived state needed.
      return base;
    }

    case "training_started": {
      const job: TrainingJob = {
        job_id: event.job_id,
        status: "started",
        base_model: event.base_model,
        example_count: event.example_count,
        started_at: event.timestamp,
        updated_at: event.timestamp,
      };
      const training = [job, ...state.training.filter((t) => t.job_id !== job.job_id)];
      return { ...base, training };
    }

    case "training_status": {
      const existing = state.training.find((t) => t.job_id === event.job_id);
      const job: TrainingJob = {
        job_id: event.job_id,
        status: event.status,
        base_model: existing?.base_model,
        example_count: existing?.example_count,
        model_id: event.model_id ?? existing?.model_id,
        started_at: existing?.started_at ?? event.timestamp,
        updated_at: event.timestamp,
      };
      const training = [job, ...state.training.filter((t) => t.job_id !== job.job_id)];
      return { ...base, training };
    }

    case "receipts_updated": {
      return { ...base, receiptsVersion: state.receiptsVersion + 1 };
    }

    default: {
      // Exhaustiveness guard: if a new event type is added to the contract and
      // not handled here, TypeScript flags it at compile time.
      const _never: never = event;
      void _never;
      return base;
    }
  }
}

function reducer(state: EngineState, action: Action): EngineState {
  switch (action.kind) {
    case "status":
      return { ...state, status: action.status };
    case "hydrated":
      return { ...state, hydrated: true };
    case "event":
      return applyEvent(state, action.event);
    case "hydrate": {
      // Apply oldest-first so derived streaks fold in chronological order.
      const ordered = [...action.events].sort((a, b) =>
        a.timestamp.localeCompare(b.timestamp),
      );
      let next = state;
      for (const ev of ordered) next = applyEvent(next, ev);
      return { ...next, hydrated: true };
    }
    default:
      return state;
  }
}

function isEngineEvent(value: unknown): value is EngineEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string" &&
    typeof (value as { timestamp?: unknown }).timestamp === "string"
  );
}

/**
 * Connects to the engine's WS stream, hydrates history from GET /events, and
 * reconnects with capped exponential backoff. Returns the folded engine state.
 */
export function useEngine(): EngineState {
  const [state, dispatch] = useReducer(reducer, initialState);
  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    closedRef.current = false;

    // One-shot history hydration. If it fails, we simply rely on the live
    // stream — we never substitute invented history.
    void (async () => {
      try {
        const res = await apiFetch("/events");
        if (!res.ok) throw new Error(`hydrate ${res.status}`);
        const body: unknown = await res.json();
        const list = Array.isArray(body)
          ? body
          : Array.isArray((body as { events?: unknown }).events)
            ? (body as { events: unknown[] }).events
            : [];
        const events = list.filter(isEngineEvent);
        dispatch({ kind: "hydrate", events });
      } catch {
        dispatch({ kind: "hydrated" });
      }
    })();

    const connect = (): void => {
      if (closedRef.current) return;
      dispatch({ kind: "status", status: "connecting" });

      let socket: WebSocket;
      try {
        socket = new WebSocket(engineWebSocketUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        attemptRef.current = 0;
        dispatch({ kind: "status", status: "online" });
      };

      socket.onmessage = (msg: MessageEvent<string>) => {
        try {
          const parsed: unknown = JSON.parse(msg.data);
          if (isEngineEvent(parsed)) dispatch({ kind: "event", event: parsed });
        } catch {
          // A malformed frame is dropped, not guessed at.
        }
      };

      socket.onerror = () => {
        socket.close();
      };

      socket.onclose = () => {
        socketRef.current = null;
        if (closedRef.current) return;
        dispatch({ kind: "status", status: "offline" });
        scheduleReconnect();
      };
    };

    const scheduleReconnect = (): void => {
      if (closedRef.current) return;
      const attempt = attemptRef.current++;
      const delay = Math.min(1000 * 2 ** attempt, 15000);
      timerRef.current = window.setTimeout(connect, delay);
    };

    connect();

    return () => {
      closedRef.current = true;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, []);

  return state;
}

function eventIdentity(event: EngineEvent): string {
  const record = event as EngineEvent & {
    claim_id?: string;
    agent_id?: string;
    job_id?: string;
  };
  return [
    event.type,
    event.timestamp,
    record.claim_id ?? "",
    record.agent_id ?? "",
    record.job_id ?? "",
  ].join(":");
}

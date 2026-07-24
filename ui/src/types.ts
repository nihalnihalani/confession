/**
 * THE AUTHORITATIVE EVENT CONTRACT.
 *
 * This file mirrors the engine's WS/REST event types exactly. The engine
 * (engine/confession/events.py) emits these; the UI renders ONLY these.
 * REALNESS LAW: there is no invented event path anywhere in the UI — every
 * value that reaches the screen originated from a real engine emission.
 *
 * Contract changes land here and in the engine emitter together, or not at all.
 */

/** Replay's verdict on a claim. There is no fourth state and no manual override. */
export type Verdict = "VERIFIED" | "FALSE_CLAIM" | "PENDING";

/** Guild tool-grant tiers. L0 = read-only (physically cannot write). L1 = write. */
export type Tier = "L0" | "L1";

/**
 * Number of consecutive Replay-verified passes required to ratchet up a tier.
 * Mirrors the engine's ratchet threshold; used only to render streak progress.
 */
export const RATCHET_N = 3;

/** A single Replay finding, reported verbatim and linked by its real URL. */
export interface Bug {
  id?: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low" | string;
  root_cause: string;
  url?: string;
}

interface EventBase {
  /** ISO-8601 timestamp emitted by the engine. */
  timestamp: string;
}

/** A Builder (or judge) agent claims a task is complete. */
export interface ClaimSubmittedEvent extends EventBase {
  type: "claim_submitted";
  claim_id: string;
  agent_id: string;
  task_id?: string;
  task_title?: string;
  claim_text: string;
}

/** The Auditor handed the claim to Replay QA; exploration has begun. */
export interface AuditStartedEvent extends EventBase {
  type: "audit_started";
  claim_id: string;
  /** Replay project URL for this exploration run, if available yet. */
  project_url?: string;
  target_url?: string;
}

/** A live progress ping from the running Replay exploration. */
export interface AuditProgressEvent extends EventBase {
  type: "audit_progress";
  claim_id: string;
  message: string;
  /** 0..1 fraction, when the engine can estimate it. */
  progress?: number;
}

/** Replay returned a verdict. This — never the agent's word — drives everything. */
export interface VerdictReachedEvent extends EventBase {
  type: "verdict_reached";
  claim_id: string;
  agent_id: string;
  verdict: Verdict;
  /** Real Replay report URL. */
  report_url?: string;
  bugs: Bug[];
  message?: string;
}

/** A real Guild workspace tier change (promotion or demotion). */
export interface TierChangedEvent extends EventBase {
  type: "tier_changed";
  agent_id: string;
  from: Tier;
  to: Tier;
  reason: string;
}

/** A caught false claim, logged as a Pioneer fine-tune example. */
export interface LieRecordedEvent extends EventBase {
  type: "lie_recorded";
  claim_id: string;
  agent_id: string;
  claim_text: string;
  report_url?: string;
}

/** A Pioneer fine-tune job started on the accumulated caught lies. */
export interface TrainingStartedEvent extends EventBase {
  type: "training_started";
  job_id: string;
  base_model?: string;
  example_count?: number;
}

/** A status update on a running Pioneer fine-tune job. */
export interface TrainingStatusEvent extends EventBase {
  type: "training_status";
  job_id: string;
  status: string;
  /** When training completes, the job ID IS the chat model ID. */
  model_id?: string;
}

/** Authoritative ratchet state after a verdict or confirmed Guild reconciliation. */
export interface TierStateEvent extends EventBase {
  type: "tier_state";
  agent_id: string;
  current: Tier;
  streak: number;
  pending_action?: string;
  error?: string;
}

/** The receipts snapshot changed; consumers should re-fetch GET /api/receipts. */
export interface ReceiptsUpdatedEvent extends EventBase {
  type: "receipts_updated";
}

/** Discriminated union over every event the engine emits. */
export type EngineEvent =
  | ClaimSubmittedEvent
  | AuditStartedEvent
  | AuditProgressEvent
  | VerdictReachedEvent
  | TierChangedEvent
  | LieRecordedEvent
  | TrainingStartedEvent
  | TrainingStatusEvent
  | TierStateEvent
  | ReceiptsUpdatedEvent;

export type EngineEventType = EngineEvent["type"];

/* ------------------------------------------------------------------ *
 * Derived view models (built by the reducer from the event stream).  *
 * ------------------------------------------------------------------ */

/** A claim's full lifecycle, assembled from its events. */
export interface Claim {
  claim_id: string;
  agent_id: string;
  task_id?: string;
  task_title?: string;
  claim_text: string;
  submitted_at: string;
  status: Verdict;
  auditing: boolean;
  progress?: number;
  progress_message?: string;
  project_url?: string;
  target_url?: string;
  report_url?: string;
  bugs: Bug[];
  verdict_at?: string;
}

/** Per-agent tier standing, assembled from tier + verdict events. */
export interface TierState {
  agent_id: string;
  current: Tier;
  /** Consecutive VERIFIED passes since the last non-verified verdict. */
  streak: number;
  lastReason?: string;
  lastChange?: { from: Tier; to: Tier; at: string };
  pendingAction?: string;
  error?: string;
}

/** A Pioneer fine-tune job, assembled from training events. */
export interface TrainingJob {
  job_id: string;
  status: string;
  base_model?: string;
  example_count?: number;
  model_id?: string;
  started_at: string;
  updated_at: string;
}

export type ConnectionStatus = "connecting" | "online" | "offline";

/* ------------------------------------------------------------------ *
 * REST payloads.                                                     *
 * ------------------------------------------------------------------ */

/** GET /api/receipts — live proof state, nothing that requires trusting us. */
export interface ReceiptsData {
  replay: ReplayReceipt[];
  guild: GuildReceipt[];
  pioneer: PioneerReceipt[];
}

export interface ReplayReceipt {
  report_url: string;
  claim_id?: string;
  verdict?: Verdict;
  created_at?: string;
}

export interface GuildReceipt {
  agent_id: string;
  tier: Tier | string;
  session_note?: string;
  session_url?: string;
}

export interface PioneerReceipt {
  job_id: string;
  status: string;
  started_at?: string;
  model_id?: string;
}

/** A task the target-app Builder can be asked to complete (GET /api/tasks). */
export interface TaskOption {
  id: string;
  title: string;
}

/** POST /api/claims request body. */
export interface SubmitClaimBody {
  agent_id: string;
  task_id: string;
  claim_text: string;
}

export interface JobData {
  id: string;
  kind: "audit" | "builder" | "training" | string;
  status: "queued" | "running" | "succeeded" | "failed" | "interrupted" | string;
  payload: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface HealthData {
  status: "ready" | "degraded";
  time: string;
  environment: string;
  components: Record<string, boolean>;
}

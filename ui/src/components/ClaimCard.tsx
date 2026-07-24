import type { Claim } from "../types";
import { BugReport } from "./BugReport";

/**
 * One claim's lifecycle card: who claimed, what they claimed, and the current
 * status. PENDING pulses amber; VERIFIED goes green; FALSE_CLAIM slams in a red
 * "CLAIM FALSE" banner. While auditing it shows the live Replay scan indicator.
 */
export function ClaimCard({ claim }: { claim: Claim }): JSX.Element {
  const status = claim.status;
  const isFalse = status === "FALSE_CLAIM";

  return (
    <article className={`claim claim--${status.toLowerCase()}`}>
      {isFalse ? (
        <div className="claim__slam" role="alert">
          CLAIM FALSE
        </div>
      ) : null}

      <header className="claim__head">
        <div className="claim__who">
          <span className="avatar" aria-hidden="true">
            {initials(claim.agent_id)}
          </span>
          <div className="claim__meta">
            <span className="claim__agent">{claim.agent_id}</span>
            <span className="claim__task">
              {claim.task_title ?? claim.task_id ?? "task"}
            </span>
            <time className="claim__time mono" dateTime={claim.submitted_at}>
              {formatTime(claim.submitted_at)}
            </time>
          </div>
        </div>
        <StatusChip claim={claim} />
      </header>

      <p className="claim__text">
        <span className="claim__oath mono" aria-hidden="true">
          CLAIM
        </span>
        <span className="mono">{claim.claim_text || "Done."}</span>
      </p>

      {claim.auditing ? (
        <div className="claim__scan">
          <span className="scanbar" aria-hidden="true">
            <span className="scanbar__beam" />
          </span>
          <span className="claim__scanlabel mono">
            {claim.progress_message ?? "Verifying via Replay QA…"}
          </span>
        </div>
      ) : null}

      {!claim.auditing && status === "PENDING" && claim.progress_message ? (
        <p className="claim__pending-note mono">{claim.progress_message}</p>
      ) : null}

      {claim.target_url || claim.project_url ? (
        <div className="claim__links mono">
          {claim.target_url ? (
            <a href={claim.target_url} target="_blank" rel="noreferrer">
              deployed target ↗
            </a>
          ) : null}
          {claim.project_url ? (
            <a href={claim.project_url} target="_blank" rel="noreferrer">
              Replay project ↗
            </a>
          ) : null}
        </div>
      ) : null}

      {(status === "VERIFIED" || status === "FALSE_CLAIM") ? (
        <div className="claim__verdict">
          <BugReport bugs={claim.bugs} reportUrl={claim.report_url} />
        </div>
      ) : null}
    </article>
  );
}

function StatusChip({ claim }: { claim: Claim }): JSX.Element {
  const status = claim.status;
  if (status === "VERIFIED") {
    return <span className="chip chip--verified">VERIFIED</span>;
  }
  if (status === "FALSE_CLAIM") {
    return <span className="chip chip--false">FALSE CLAIM</span>;
  }
  return (
    <span className={`chip chip--pending ${claim.auditing ? "chip--auditing" : ""}`}>
      <span className="chip__dot" aria-hidden="true" />
      PENDING
    </span>
  );
}

function initials(agentId: string): string {
  const cleaned = agentId.replace(/[^a-zA-Z0-9]/g, " ").trim();
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

import { AccessPanel } from "./components/AccessPanel";
import { ClaimCard } from "./components/ClaimCard";
import { JudgeSubmit } from "./components/JudgeSubmit";
import { Operations } from "./components/Operations";
import { Polygraph } from "./components/Polygraph";
import { Receipts } from "./components/Receipts";
import { SystemStatus } from "./components/SystemStatus";
import { TierLadder } from "./components/TierLadder";
import type { ConnectionStatus } from "./types";
import { useEngine } from "./useEngine";
import { useTasks } from "./useTasks";

export default function App(): JSX.Element {
  const engine = useEngine();
  const tasks = useTasks();
  let verified = 0;
  let falseClaims = 0;
  let pending = 0;
  let activeAudits = 0;
  for (const claim of engine.claims) {
    if (claim.status === "VERIFIED") verified += 1;
    if (claim.status === "FALSE_CLAIM") falseClaims += 1;
    if (claim.status === "PENDING") pending += 1;
    if (claim.auditing) activeAudits += 1;
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to control room
      </a>
      <header className="topbar">
        <a className="brand" href="#main-content" aria-label="CONFESSION home">
          <span className="brand__seal" aria-hidden="true">
            C
          </span>
          <span className="brand__copy">
            <span className="brand__mark">CONFESSION</span>
            <span className="brand__tag">Agent accountability system</span>
          </span>
        </a>
        <div className="topbar__right">
          <nav className="topnav" aria-label="Control room">
            <a href="#evidence">Evidence</a>
            <a href="#operations">Operations</a>
            <a href="#receipts">Receipts</a>
          </nav>
          <ConnectionBadge status={engine.status} />
        </div>
      </header>

      <main id="main-content">
        <section className="hero">
          <div className="hero__copy">
            <div className="hero__kicker">
              <span className="eyebrow">Casefile 001 / live autonomy</span>
              <span className="hero__rule" aria-hidden="true" />
              <span className="mono">
                {activeAudits > 0
                  ? `${activeAudits} audit${activeAudits === 1 ? "" : "s"} in flight`
                  : "Evidence channel standing by"}
              </span>
            </div>
            <h1>
              Every claim
              <br /> enters <em>evidence.</em>
            </h1>
            <p>
              A Builder’s word changes nothing. Replay inspects the deployed product;
              its verdict alone controls Guild access and Pioneer evolution.
            </p>
            <ol className="pipeline" aria-label="Autonomous accountability pipeline">
              <PipelineStep number="01" sponsor="Replay" label="Proves the claim" />
              <PipelineStep number="02" sponsor="Guild" label="Changes the keys" />
              <PipelineStep number="03" sponsor="Pioneer" label="Learns from the lie" />
            </ol>
          </div>
          <div className="hero__metrics" aria-label="Claim summary">
            <header className="hero__metrics-head">
              <span className="eyebrow">Live ledger</span>
              <span className="mono">All-time evidence</span>
            </header>
            <div className="hero__metrics-grid">
              <Metric label="Claims" value={engine.claims.length} tone="neutral" />
              <Metric label="Verified" value={verified} tone="good" />
              <Metric label="Caught" value={falseClaims} tone="danger" />
              <Metric label="Pending" value={pending} tone="warning" />
            </div>
          </div>
        </section>

        <AccessPanel />

        <div className="workspace" id="evidence">
          <section className="evidence" aria-label="Live claim evidence">
            <Polygraph
              lastVerdict={engine.lastVerdict}
              auditing={activeAudits > 0}
              activeAudits={activeAudits}
            />
            <header className="section-head">
              <div>
                <span className="section-index mono">01</span>
                <div>
                  <span className="eyebrow">Claim ledger</span>
                  <h2>Live testimony</h2>
                </div>
              </div>
              <span className="section-head__count mono">
                {engine.claims.length.toString().padStart(2, "0")} records
              </span>
            </header>
            <div className="feed__claims">
              {engine.claims.length === 0 ? (
                <EmptyFeed hydrated={engine.hydrated} status={engine.status} />
              ) : (
                engine.claims.map((claim) => (
                  <ClaimCard key={claim.claim_id} claim={claim} />
                ))
              )}
            </div>
          </section>

          <aside
            className="rail"
            id="operations"
            aria-label="System and operator controls"
          >
            <SystemStatus />
            <Operations tasks={tasks} />
            <TierLadder tiers={engine.tiers} />
          </aside>
        </div>

        <div id="receipts">
          <Receipts version={engine.receiptsVersion} />
        </div>
        <div id="judge">
          <JudgeSubmit tasks={tasks} />
        </div>
      </main>

      <footer className="footer">
        <span className="footer__brand">CONFESSION</span>
        <span className="mono">Replay verdict → Guild grant → Pioneer evolution</span>
        <span className="footer__truth mono">No manual override</span>
      </footer>
    </div>
  );
}

function PipelineStep({
  number,
  sponsor,
  label,
}: {
  number: string;
  sponsor: string;
  label: string;
}): JSX.Element {
  return (
    <li className="pipeline__step">
      <span className="pipeline__number mono">{number}</span>
      <span>
        <strong>{sponsor}</strong>
        <small>{label}</small>
      </span>
    </li>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "neutral" | "good" | "danger" | "warning";
}): JSX.Element {
  return (
    <div className={`metric metric--${tone}`}>
      <span className="metric__value">{value.toString().padStart(2, "0")}</span>
      <span className="metric__label mono">{label}</span>
    </div>
  );
}

function EmptyFeed({
  hydrated,
  status,
}: {
  hydrated: boolean;
  status: ConnectionStatus;
}): JSX.Element {
  if (status === "offline") {
    return (
      <div className="empty">
        <span className="empty__code mono">NO SIGNAL</span>
        <p className="empty__title">Engine connection lost</p>
        <p className="empty__sub">
          The dashboard will reconnect automatically. No evidence is manufactured while
          the engine is unreachable.
        </p>
      </div>
    );
  }
  return (
    <div className="empty">
      <span className="empty__stamp" aria-hidden="true">
        0
      </span>
      <span className="empty__code mono">
        {hydrated ? "LEDGER READY" : "OPENING LEDGER"}
      </span>
      <p className="empty__title">
        {hydrated ? "No claims under examination" : "Loading recorded evidence"}
      </p>
      <p className="empty__sub">
        {hydrated
          ? "Start the autonomous Builder or enter a judge claim. The first real engine event will appear here."
          : "The dashboard is hydrating from the engine’s durable event history."}
      </p>
      {hydrated ? (
        <div className="empty__actions">
          <a href="#operations">Open operator controls ↓</a>
          <a href="#judge">Submit a judge claim ↓</a>
        </div>
      ) : null}
    </div>
  );
}

function ConnectionBadge({ status }: { status: ConnectionStatus }): JSX.Element {
  const label =
    status === "online" ? "LIVE ENGINE" : status === "connecting" ? "CONNECTING" : "OFFLINE";
  return (
    <div className={`connbadge connbadge--${status}`} role="status">
      <span className="connbadge__dot" aria-hidden="true" />
      <span className="connbadge__label">{label}</span>
    </div>
  );
}

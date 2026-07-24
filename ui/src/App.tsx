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
  const anyAuditing = engine.claims.some((claim) => claim.auditing);
  const verified = engine.claims.filter((claim) => claim.status === "VERIFIED").length;
  const falseClaims = engine.claims.filter(
    (claim) => claim.status === "FALSE_CLAIM",
  ).length;
  const pending = engine.claims.filter((claim) => claim.status === "PENDING").length;

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="CONFESSION home">
          <span className="brand__mark">CONFESSION</span>
          <span className="brand__tag">The evidence decides who keeps the keys.</span>
        </a>
        <ConnectionBadge status={engine.status} />
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero__copy">
            <span className="eyebrow">Autonomous agent accountability</span>
            <h1>
              Every claim enters
              <br />
              <em>evidence.</em>
            </h1>
            <p>
              Builder says “done.” Replay explores the deployed app. Only the
              resulting verdict can change Guild tool grants or enter Pioneer training.
            </p>
          </div>
          <div className="hero__metrics" aria-label="Claim summary">
            <Metric label="Claims" value={engine.claims.length} tone="neutral" />
            <Metric label="Verified" value={verified} tone="good" />
            <Metric label="Caught" value={falseClaims} tone="danger" />
            <Metric label="Pending" value={pending} tone="warning" />
          </div>
        </section>

        <AccessPanel />

        <div className="workspace">
          <section className="evidence" aria-label="Live claim evidence">
            <Polygraph lastVerdict={engine.lastVerdict} auditing={anyAuditing} />
            <header className="section-head">
              <div>
                <span className="eyebrow">Claim ledger</span>
                <h2>Live testimony</h2>
              </div>
              <span className="section-head__count mono">{engine.claims.length} records</span>
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

          <aside className="rail" aria-label="System and operator controls">
            <SystemStatus />
            <Operations tasks={tasks} />
            <TierLadder tiers={engine.tiers} />
          </aside>
        </div>

        <Receipts version={engine.receiptsVersion} />
        <JudgeSubmit tasks={tasks} />
      </main>

      <footer className="footer">
        <span>CONFESSION</span>
        <span className="mono">Replay verdict → Guild grant → Pioneer evolution</span>
      </footer>
    </div>
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
      <span className="empty__code mono">{hydrated ? "LEDGER EMPTY" : "OPENING LEDGER"}</span>
      <p className="empty__title">No claims under examination</p>
      <p className="empty__sub">
        Run the Builder or submit a judge claim. The first real engine event will appear
        here.
      </p>
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

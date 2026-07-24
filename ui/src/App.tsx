import { ClaimCard } from "./components/ClaimCard";
import { JudgeSubmit } from "./components/JudgeSubmit";
import { Polygraph } from "./components/Polygraph";
import { Receipts } from "./components/Receipts";
import { TierLadder } from "./components/TierLadder";
import { useEngine } from "./useEngine";
import type { ConnectionStatus } from "./types";

export default function App(): JSX.Element {
  const engine = useEngine();
  const anyAuditing = engine.claims.some((c) => c.auditing);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark">CONFESSION</span>
          <span className="brand__tag">We don't trust agents. We catch them.</span>
        </div>
        <ConnectionBadge status={engine.status} />
      </header>

      <main className="grid">
        <section className="feed" aria-label="Claim feed">
          <div className="feed__polygraph">
            <Polygraph lastVerdict={engine.lastVerdict} auditing={anyAuditing} />
          </div>

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

        <aside className="rail" aria-label="Tier ladder">
          <TierLadder tiers={engine.tiers} />
        </aside>
      </main>

      <section className="bottom">
        <Receipts version={engine.receiptsVersion} />
      </section>

      <div className="dock">
        <JudgeSubmit />
      </div>
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
        <span className="empty__icon" aria-hidden="true">
          ⚠
        </span>
        <p className="empty__title">Engine offline</p>
        <p className="empty__sub mono">
          No live event stream. Start the engine (uvicorn, port 8000) — this UI
          renders only real data, so there is nothing to show until it's up.
        </p>
      </div>
    );
  }
  return (
    <div className="empty">
      <span className="empty__icon" aria-hidden="true">
        {hydrated ? "◎" : "…"}
      </span>
      <p className="empty__title">No claims yet — submit one below</p>
      <p className="empty__sub mono">
        The moment an agent claims "done," it appears here and Replay starts auditing.
      </p>
    </div>
  );
}

function ConnectionBadge({ status }: { status: ConnectionStatus }): JSX.Element {
  const label =
    status === "online" ? "LIVE" : status === "connecting" ? "CONNECTING" : "OFFLINE";
  return (
    <div className={`connbadge connbadge--${status}`}>
      <span className="connbadge__dot" aria-hidden="true" />
      <span className="connbadge__label">{label}</span>
    </div>
  );
}

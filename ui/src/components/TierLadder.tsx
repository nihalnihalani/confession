import { RATCHET_N, type TierState } from "../types";

/**
 * Per-agent tool-grant ladder. L0 = read-only (lock), L1 = write (key). On a
 * real tier_changed the current rung reflects the new grant; the streak bar
 * shows progress toward the next promotion (RATCHET_N consecutive verifieds).
 * Reflects real Guild workspace state — this is a mirror, not the source.
 */
export function TierLadder({
  tiers,
}: {
  tiers: Record<string, TierState>;
}): JSX.Element {
  const agents = Object.values(tiers).sort((a, b) =>
    a.agent_id.localeCompare(b.agent_id),
  );

  return (
    <section className="ladder" aria-label="Tool-grant tiers">
      <h2 className="rail__title">Tool grants</h2>
      {agents.length === 0 ? (
        <p className="rail__empty">No agents yet. Tiers appear as claims are audited.</p>
      ) : (
        <ul className="ladder__list">
          {agents.map((agent) => (
            <AgentTier key={agent.agent_id} agent={agent} />
          ))}
        </ul>
      )}
    </section>
  );
}

function AgentTier({ agent }: { agent: TierState }): JSX.Element {
  const atL1 = agent.current === "L1";
  const justChanged = agent.lastChange;
  const promoted = justChanged && justChanged.to === "L1";
  const demoted = justChanged && justChanged.to === "L0";

  return (
    <li className={`atier atier--${agent.current.toLowerCase()}`}>
      <div className="atier__head">
        <span className="atier__agent mono">{agent.agent_id}</span>
        <span className={`atier__badge ${atL1 ? "atier__badge--l1" : "atier__badge--l0"}`}>
          {agent.current}
        </span>
      </div>

      <div className="atier__rungs">
        <Rung
          label="L1"
          sub="write"
          active={atL1}
          icon="key"
          animate={promoted ? "promote" : undefined}
        />
        <Rung
          label="L0"
          sub="read-only"
          active={!atL1}
          icon="lock"
          animate={demoted ? "demote" : undefined}
        />
      </div>

      {atL1 ? (
        <p className="atier__note mono">Write tools granted.</p>
      ) : (
        <div className="atier__progress">
          <div className="atier__progresslabel mono">
            {agent.streak}/{RATCHET_N} verified — streak to promotion
          </div>
          <div className="atier__bar">
            {Array.from({ length: RATCHET_N }, (_, i) => (
              <span
                key={i}
                className={`atier__pip ${i < agent.streak ? "atier__pip--on" : ""}`}
              />
            ))}
          </div>
        </div>
      )}

      {agent.lastReason ? (
        <p className="atier__reason mono">{agent.lastReason}</p>
      ) : null}
      {agent.pendingAction ? (
        <p className="atier__pending mono" role="status">
          Guild {agent.pendingAction} pending
          {agent.error ? ` · ${agent.error}` : ""}
        </p>
      ) : null}
    </li>
  );
}

function Rung({
  label,
  sub,
  active,
  icon,
  animate,
}: {
  label: string;
  sub: string;
  active: boolean;
  icon: "lock" | "key";
  animate?: "promote" | "demote";
}): JSX.Element {
  return (
    <div
      className={`rung ${active ? "rung--active" : ""} ${animate ? `rung--${animate}` : ""}`}
    >
      <span className="rung__icon" aria-hidden="true">
        {icon === "lock" ? "🔒" : "🔑"}
      </span>
      <span className="rung__label">{label}</span>
      <span className="rung__sub">{sub}</span>
    </div>
  );
}

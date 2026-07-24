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
      <header className="ladder__head">
        <div>
          <span className="eyebrow">Guild / capability boundary</span>
          <h2 className="rail__title">Tool grants</h2>
        </div>
        <span className="ladder__count mono">{agents.length}</span>
      </header>
      {agents.length === 0 ? (
        <div className="rail__empty">
          <span className="rail__empty-icon" aria-hidden="true">
            —
          </span>
          <p>No agents under policy yet.</p>
          <small>Tiers appear after a Builder claim enters evidence.</small>
        </div>
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
        <span>
          <small className="mono">Agent</small>
          <strong className="atier__agent mono">{agent.agent_id}</strong>
        </span>
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
        <TierGlyph icon={icon} />
      </span>
      <span className="rung__label">{label}</span>
      <span className="rung__sub">{sub}</span>
    </div>
  );
}

function TierGlyph({ icon }: { icon: "lock" | "key" }): JSX.Element {
  if (icon === "lock") {
    return (
      <svg viewBox="0 0 20 20">
        <rect x="4" y="9" width="12" height="8" rx="1" />
        <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20">
      <circle cx="7" cy="8" r="3.5" />
      <path d="m9.5 10.5 6 6m-2-2 1.8-1.8m-4 0 1.8-1.8" />
    </svg>
  );
}

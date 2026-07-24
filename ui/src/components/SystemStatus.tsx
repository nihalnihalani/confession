import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import type { HealthData } from "../types";

export function SystemStatus(): JSX.Element {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    let active = true;
    const load = async (): Promise<void> => {
      try {
        const response = await apiFetch("/health");
        if (!response.ok) throw new Error(String(response.status));
        const body = (await response.json()) as HealthData;
        if (active) {
          setHealth(body);
          setReachable(true);
        }
      } catch {
        if (active) setReachable(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const components = health ? Object.entries(health.components) : [];
  const readyCount = components.reduce((count, [, ready]) => count + Number(ready), 0);
  const isReady = reachable && health?.status === "ready";

  return (
    <section className="panel system" aria-label="System readiness">
      <header className="panel__head">
        <div>
          <span className="eyebrow">Runtime / live dependencies</span>
          <h2 className="panel__title">System pulse</h2>
        </div>
        <span
          className={`status-word ${isReady ? "status-word--good" : "status-word--warn"}`}
        >
          {!reachable ? "offline" : isReady ? "ready" : health?.status ?? "checking"}
        </span>
      </header>
      <div className="system__summary">
        <strong>{components.length > 0 ? `${readyCount}/${components.length}` : "—"}</strong>
        <span>
          {!reachable
            ? "Engine cannot be reached"
            : isReady
              ? "All dependencies reporting"
              : "Dependencies need attention"}
        </span>
      </div>
      <div className="system__grid">
        {components.length === 0 ? (
          <p className="panel__empty mono">Waiting for the engine health report…</p>
        ) : (
          components.map(([name, ready]) => (
            <div className="system__item" key={name}>
              <span
                className={`system__lamp ${ready ? "system__lamp--on" : ""}`}
                aria-hidden="true"
              />
              <span className="system__name">{componentLabel(name)}</span>
              <span className="system__value mono">{ready ? "online" : "needed"}</span>
            </div>
          ))
        )}
      </div>
      {health?.time ? (
        <time className="system__time mono" dateTime={health.time}>
          Checked {formatTime(health.time)}
        </time>
      ) : null}
    </section>
  );
}

const COMPONENT_LABELS: Record<string, string> = {
  database: "Evidence database",
  state_dir: "Durable state",
  replay: "Replay QA",
  target_app: "Target application",
  pioneer: "Pioneer",
  auth: "Access control",
  guild_grants: "Guild grants",
  dashboard: "Dashboard",
};

function componentLabel(name: string): string {
  return COMPONENT_LABELS[name] ?? name.replaceAll("_", " ");
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

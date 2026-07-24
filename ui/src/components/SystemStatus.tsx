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
  return (
    <section className="panel system" aria-label="System readiness">
      <header className="panel__head">
        <div>
          <span className="eyebrow">Runtime</span>
          <h2 className="panel__title">System readiness</h2>
        </div>
        <span
          className={`status-word ${
            reachable && health?.status === "ready" ? "status-word--good" : "status-word--warn"
          }`}
        >
          {!reachable ? "unreachable" : health?.status ?? "checking"}
        </span>
      </header>
      <div className="system__grid">
        {components.length === 0 ? (
          <p className="panel__empty mono">Waiting for the engine health report…</p>
        ) : (
          components.map(([name, ready]) => (
            <div className="system__item" key={name}>
              <span className={`system__lamp ${ready ? "system__lamp--on" : ""}`} />
              <span>{name.replaceAll("_", " ")}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

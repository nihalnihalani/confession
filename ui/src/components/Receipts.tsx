import { useCallback, useEffect, useRef, useState } from "react";
import type { ReceiptsData } from "../types";

/**
 * "Nothing here requires trusting us." Polls GET /api/receipts every 5s and
 * also re-fetches whenever a receipts_updated event bumps `version`. Three
 * columns of live proof: Replay report URLs, Guild tier/session state, and the
 * Pioneer training.jsonl tail. No values are ever invented — if the endpoint is
 * empty, the columns say so.
 */
export function Receipts({ version }: { version: number }): JSX.Element {
  const [data, setData] = useState<ReceiptsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const load = useCallback(async (): Promise<void> => {
    try {
      const res = await fetch("/api/receipts", { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`receipts ${res.status}`);
      const body = (await res.json()) as Partial<ReceiptsData>;
      if (!mounted.current) return;
      setData({
        replay: body.replay ?? [],
        guild: body.guild ?? [],
        pioneer: body.pioneer ?? [],
      });
      setError(null);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : "failed to load receipts");
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    const id = window.setInterval(() => void load(), 5000);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
    };
  }, [load]);

  // Re-fetch immediately when the engine signals a receipts change.
  useEffect(() => {
    if (version > 0) void load();
  }, [version, load]);

  return (
    <section className="receipts" aria-label="Receipts">
      <header className="receipts__head">
        <h2 className="receipts__title">Receipts</h2>
        <p className="receipts__sub">Nothing here requires trusting us.</p>
        {error ? <span className="receipts__err mono">offline: {error}</span> : null}
      </header>

      <div className="receipts__cols">
        <div className="rcol">
          <h3 className="rcol__title">Replay</h3>
          {!data || data.replay.length === 0 ? (
            <p className="rcol__empty">No verdicts recorded yet.</p>
          ) : (
            <ul className="rcol__list">
              {data.replay.map((r, i) => (
                <li className="rrow" key={`${r.report_url}-${i}`}>
                  <a className="rrow__link mono" href={r.report_url} target="_blank" rel="noreferrer">
                    {shortUrl(r.report_url)}
                  </a>
                  <span className="rrow__meta mono">
                    {r.verdict ?? ""}
                    {r.created_at ? ` · ${fmt(r.created_at)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rcol">
          <h3 className="rcol__title">Guild</h3>
          {!data || data.guild.length === 0 ? (
            <p className="rcol__empty">No tier state yet.</p>
          ) : (
            <ul className="rcol__list">
              {data.guild.map((g, i) => (
                <li className="rrow" key={`${g.agent_id}-${i}`}>
                  <span className="rrow__link mono">
                    {g.agent_id} → <strong>{g.tier}</strong>
                  </span>
                  {g.session_note ? (
                    <span className="rrow__meta mono">{g.session_note}</span>
                  ) : null}
                  {g.session_url ? (
                    <a className="rrow__meta mono" href={g.session_url} target="_blank" rel="noreferrer">
                      session →
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rcol">
          <h3 className="rcol__title">Pioneer</h3>
          {!data || data.pioneer.length === 0 ? (
            <p className="rcol__empty">No training jobs yet.</p>
          ) : (
            <ul className="rcol__list">
              {data.pioneer.map((p, i) => (
                <li className="rrow" key={`${p.job_id}-${i}`}>
                  <span className="rrow__link mono">{p.job_id}</span>
                  <span className="rrow__meta mono">
                    {p.status}
                    {p.started_at ? ` · started ${fmt(p.started_at)}` : ""}
                    {p.model_id ? ` · model ${p.model_id}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname}`.replace(/\/$/, "");
  } catch {
    return url;
  }
}

function fmt(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
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
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const mounted = useRef(true);

  const load = useCallback(async (): Promise<void> => {
    try {
      const res = await apiFetch("/api/receipts");
      if (!res.ok) throw new Error(`receipts ${res.status}`);
      const body = (await res.json()) as Partial<ReceiptsData>;
      if (!mounted.current) return;
      setData({
        replay: body.replay ?? [],
        guild: body.guild ?? [],
        pioneer: body.pioneer ?? [],
      });
      setError(null);
      setLastUpdated(new Date());
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
    <section className="receipts" aria-label="Receipts" aria-busy={!data && !error}>
      <header className="receipts__head">
        <div className="receipts__heading">
          <span className="section-index mono">02</span>
          <div>
            <span className="eyebrow">External proof / live links</span>
            <h2 className="receipts__title">Receipts, not promises.</h2>
          </div>
        </div>
        <div className="receipts__status mono">
          {error ? (
            <span className="receipts__err">Offline · {error}</span>
          ) : lastUpdated ? (
            <span>Updated {formatClock(lastUpdated)}</span>
          ) : (
            <span>Loading live receipts…</span>
          )}
          <span className="receipts__pulse" aria-hidden="true" />
        </div>
      </header>

      <div className="receipts__cols">
        <div className="rcol">
          <ProviderHead
            number="01"
            name="Replay"
            description="Independent QA verdicts"
            count={data?.replay.length}
          />
          {!data ? (
            <ReceiptLoading />
          ) : data.replay.length === 0 ? (
            <ReceiptEmpty label="No verdicts recorded yet." />
          ) : (
            <ul className="rcol__list">
              {data.replay.map((r, i) => (
                <li className="rrow" key={r.claim_id ?? `${r.report_url}-${i}`}>
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
          <ProviderHead
            number="02"
            name="Guild"
            description="Auditable tool grants"
            count={data?.guild.length}
          />
          {!data ? (
            <ReceiptLoading />
          ) : data.guild.length === 0 ? (
            <ReceiptEmpty label="No tier state yet." />
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
          <ProviderHead
            number="03"
            name="Pioneer"
            description="Fine-tune lineage"
            count={data?.pioneer.length}
          />
          {!data ? (
            <ReceiptLoading />
          ) : data.pioneer.length === 0 ? (
            <ReceiptEmpty label="No training jobs yet." />
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

function ProviderHead({
  number,
  name,
  description,
  count,
}: {
  number: string;
  name: string;
  description: string;
  count?: number;
}): JSX.Element {
  return (
    <header className="rcol__head">
      <span className="rcol__number mono">{number}</span>
      <span>
        <h3 className="rcol__title">{name}</h3>
        <small>{description}</small>
      </span>
      <span className="rcol__count mono">{count ?? "—"}</span>
    </header>
  );
}

function ReceiptEmpty({ label }: { label: string }): JSX.Element {
  return (
    <div className="rcol__empty">
      <span aria-hidden="true">○</span>
      <p>{label}</p>
      <small>Real evidence will appear automatically.</small>
    </div>
  );
}

function ReceiptLoading(): JSX.Element {
  return (
    <div className="rcol__empty rcol__empty--loading">
      <span className="loading-ring" aria-hidden="true" />
      <p>Reading the evidence ledger…</p>
    </div>
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

function formatClock(date: Date): string {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

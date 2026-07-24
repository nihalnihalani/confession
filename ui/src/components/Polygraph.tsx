import type { Verdict } from "../types";

/**
 * Evidence instrument driven only by real audit state. The in-flight sweep is CSS-only
 * so it does not force React to render on every animation frame.
 */
export function Polygraph({
  lastVerdict,
  auditing,
  activeAudits,
}: {
  lastVerdict?: { verdict: Verdict; at: string };
  auditing: boolean;
  activeAudits: number;
}): JSX.Element {
  const verdict = lastVerdict?.verdict;
  const angle = verdict === "FALSE_CLAIM" ? 46 : verdict === "VERIFIED" ? -42 : 0;
  const state =
    verdict === "FALSE_CLAIM"
      ? "false"
      : verdict === "VERIFIED"
        ? "verified"
        : auditing
          ? "auditing"
          : "idle";

  return (
    <div className={`polygraph polygraph--${state}`}>
      <header className="polygraph__caption">
        <div>
          <span className="eyebrow">Live evidence instrument</span>
          <strong aria-live="polite">
            {state === "false"
              ? "DECEPTION DETECTED"
              : state === "verified"
                ? "CLAIM VERIFIED"
                : state === "auditing"
                  ? "REPLAY MEASURING"
                  : "AWAITING SIGNAL"}
          </strong>
        </div>
        <span className="polygraph__meta mono">
          {state === "false"
            ? "Verdict: false claim"
            : state === "verified"
              ? "Verdict: verified"
              : auditing
                ? `${activeAudits} active audit${activeAudits === 1 ? "" : "s"}`
                : lastVerdict
                  ? `Last verdict ${formatTime(lastVerdict.at)}`
                  : "No verdict recorded"}
        </span>
      </header>
      <svg
        viewBox="0 0 320 180"
        className="polygraph__svg"
        role="img"
        aria-label={`Polygraph state: ${state}`}
      >
        <defs>
          <linearGradient id="pg-trace" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--pg-trace-a)" />
            <stop offset="100%" stopColor="var(--pg-trace-b)" />
          </linearGradient>
        </defs>
        {[45, 90, 135].map((y) => (
          <line key={y} x1="12" y1={y} x2="308" y2={y} className="polygraph__grid" />
        ))}
        <path d={tracePath(angle)} className="polygraph__trace" fill="none" />
        <g transform="translate(160 150)">
          <path d="M -120 0 A 120 120 0 0 1 120 0" className="polygraph__dial" fill="none" />
          <g
            className="polygraph__needle-group"
            style={{ transform: `rotate(${angle}deg)` }}
          >
            <line x1="0" y1="0" x2="0" y2="-116" className="polygraph__needle" />
          </g>
          <circle cx="0" cy="0" r="7" className="polygraph__hub" />
        </g>
      </svg>
      <div className="polygraph__scale mono" aria-hidden="true">
        <span>Verified</span>
        <span>Pending</span>
        <span>False claim</span>
      </div>
    </div>
  );
}

function tracePath(angle: number): string {
  const amplitude = 6 + Math.abs(angle) * 0.9;
  const points: string[] = [];
  for (let x = 12; x <= 308; x += 8) {
    const phase = x * 0.28;
    const y = 90 - Math.sin(phase) * amplitude * (0.5 + 0.5 * Math.sin(phase * 0.37));
    points.push(`${x},${y.toFixed(1)}`);
  }
  return `M ${points.join(" L ")}`;
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

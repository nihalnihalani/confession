import { useEffect, useRef, useState } from "react";
import type { Verdict } from "../types";

/**
 * A polygraph needle, purely presentational. It idles (gentle sweep) while an
 * audit is running, spikes red on FALSE_CLAIM, and settles green on VERIFIED.
 * Driven ONLY by real verdict events passed in as props — never self-animates
 * a verdict that didn't happen.
 */
export function Polygraph({
  lastVerdict,
  auditing,
}: {
  lastVerdict?: { verdict: Verdict; at: string };
  auditing: boolean;
}): JSX.Element {
  const [angle, setAngle] = useState(0);
  const rafRef = useRef<number | null>(null);
  const verdict = lastVerdict?.verdict;

  // Idle sweep only while an audit is genuinely in flight.
  useEffect(() => {
    if (!auditing || verdict === "FALSE_CLAIM" || verdict === "VERIFIED") {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      return;
    }
    const start = performance.now();
    const tick = (now: number): void => {
      const t = (now - start) / 1000;
      setAngle(Math.sin(t * 3) * 18);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [auditing, verdict]);

  // Settle to a fixed deflection once a real verdict lands.
  useEffect(() => {
    if (verdict === "FALSE_CLAIM") setAngle(46);
    else if (verdict === "VERIFIED") setAngle(-42);
  }, [verdict, lastVerdict?.at]);

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
      <svg viewBox="0 0 320 180" className="polygraph__svg" role="img" aria-label="polygraph">
        <defs>
          <linearGradient id="pg-trace" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--pg-trace-a)" />
            <stop offset="100%" stopColor="var(--pg-trace-b)" />
          </linearGradient>
        </defs>

        {/* baseline grid */}
        {[45, 90, 135].map((y) => (
          <line key={y} x1="12" y1={y} x2="308" y2={y} className="polygraph__grid" />
        ))}

        {/* the trace: a jittered line whose amplitude follows the needle */}
        <path d={tracePath(angle)} className="polygraph__trace" fill="none" />

        {/* dial + needle */}
        <g transform="translate(160 150)">
          <path d="M -120 0 A 120 120 0 0 1 120 0" className="polygraph__dial" fill="none" />
          <line
            x1="0"
            y1="0"
            x2={Math.sin((angle * Math.PI) / 180) * 116}
            y2={-Math.cos((angle * Math.PI) / 180) * 116}
            className="polygraph__needle"
          />
          <circle cx="0" cy="0" r="7" className="polygraph__hub" />
        </g>
      </svg>

      <div className="polygraph__label">
        {state === "false"
          ? "DECEPTION DETECTED"
          : state === "verified"
            ? "TRUTHFUL"
            : state === "auditing"
              ? "MEASURING…"
              : "AWAITING SIGNAL"}
      </div>
    </div>
  );
}

/** Build a wobbling trace line whose peak amplitude tracks the needle angle. */
function tracePath(angle: number): string {
  const amp = 6 + Math.abs(angle) * 0.9;
  const mid = 90;
  const pts: string[] = [];
  for (let x = 12; x <= 308; x += 8) {
    const phase = x * 0.28;
    const y = mid - Math.sin(phase) * amp * (0.5 + 0.5 * Math.sin(phase * 0.37));
    pts.push(`${x},${y.toFixed(1)}`);
  }
  return `M ${pts.join(" L ")}`;
}

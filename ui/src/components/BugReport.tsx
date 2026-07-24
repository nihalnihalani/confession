import type { Bug } from "../types";

/**
 * Renders real Replay findings verbatim. We never summarize a verdict into
 * something stronger than the report says — title, severity, and root-cause
 * text are shown as returned, and the report_url is the primary evidence link.
 */
export function BugReport({
  bugs,
  reportUrl,
}: {
  bugs: Bug[];
  reportUrl?: string;
}): JSX.Element {
  return (
    <div className="bugreport">
      {bugs.length === 0 ? (
        <p className="bugreport__empty">
          Replay reported no open bugs on the claimed scope.
        </p>
      ) : (
        <ul className="bugreport__list">
          {bugs.map((bug, i) => (
            <li className="bug" key={bug.id ?? `${bug.title}-${i}`}>
              <div className="bug__head">
                <span className={`bug__sev bug__sev--${severityClass(bug.severity)}`}>
                  {bug.severity}
                </span>
                <span className="bug__title">{bug.title}</span>
              </div>
              <p className="bug__cause mono">{bug.root_cause}</p>
              {bug.url ? (
                <a className="bug__link" href={bug.url} target="_blank" rel="noreferrer">
                  Open finding →
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {reportUrl ? (
        <a className="bugreport__evidence" href={reportUrl} target="_blank" rel="noreferrer">
          View the evidence →
        </a>
      ) : null}
    </div>
  );
}

function severityClass(severity: string): string {
  const s = severity.toLowerCase();
  if (s === "critical" || s === "high" || s === "medium" || s === "low") return s;
  return "unknown";
}

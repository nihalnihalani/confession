import { useEffect, useState } from "react";
import type { SubmitClaimBody, TaskOption } from "../types";

type SubmitState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "ok"; claimId?: string }
  | { kind: "error"; message: string };

/**
 * The Autonomy-proof form. Any visitor submits a completion claim; it POSTs to
 * /api/claims and the resulting ClaimCard appears via the SAME WS stream and
 * runs the IDENTICAL real audit pipeline as internal claims. One code path,
 * zero special-casing. This is the most reliable thing we ship — "Try to lie to it."
 */
export function JudgeSubmit(): JSX.Element {
  const [tasks, setTasks] = useState<TaskOption[]>([]);
  const [taskId, setTaskId] = useState("");
  const [claimText, setClaimText] = useState("");
  const [state, setState] = useState<SubmitState>({ kind: "idle" });

  // Load real available tasks. If the endpoint isn't there, the field falls
  // back to free text — we never fabricate a task list.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await fetch("/api/tasks", { headers: { Accept: "application/json" } });
        if (!res.ok) return;
        const body: unknown = await res.json();
        if (!alive || !Array.isArray(body)) return;
        const opts = body.filter(
          (t): t is TaskOption =>
            typeof t === "object" &&
            t !== null &&
            typeof (t as TaskOption).id === "string" &&
            typeof (t as TaskOption).title === "string",
        );
        setTasks(opts);
        if (opts.length > 0 && opts[0]) setTaskId(opts[0].id);
      } catch {
        // Free-text fallback; no invented tasks.
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const trimmedTask = taskId.trim();
    const trimmedClaim = claimText.trim();
    if (!trimmedTask || !trimmedClaim) {
      setState({ kind: "error", message: "Task and claim text are both required." });
      return;
    }
    setState({ kind: "submitting" });
    const payload: SubmitClaimBody = {
      agent_id: "judge",
      task_id: trimmedTask,
      claim_text: trimmedClaim,
    };
    try {
      const res = await fetch("/api/claims", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `submit failed (${res.status})`);
      }
      const body: unknown = await res.json().catch(() => ({}));
      const claimId =
        typeof (body as { claim_id?: unknown }).claim_id === "string"
          ? (body as { claim_id: string }).claim_id
          : undefined;
      setState({ kind: "ok", claimId });
      setClaimText("");
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof Error ? err.message : "submit failed",
      });
    }
  };

  const busy = state.kind === "submitting";

  return (
    <section className="judge" aria-label="Submit a claim">
      <div className="judge__pitch">
        <h2 className="judge__title">Try to lie to it</h2>
        <p className="judge__sub">
          Submit a completion claim as <span className="mono">judge</span>. It runs
          the exact same real pipeline — Replay audits your app, the verdict decides
          the tier. Zero human clicks after you hit submit.
        </p>
      </div>

      <form className="judge__form" onSubmit={(e) => void submit(e)}>
        <label className="field">
          <span className="field__label">Task</span>
          {tasks.length > 0 ? (
            <select
              className="field__input mono"
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              disabled={busy}
            >
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="field__input mono"
              type="text"
              placeholder="task id (e.g. task-1)"
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              disabled={busy}
            />
          )}
        </label>

        <label className="field">
          <span className="field__label">Claim</span>
          <textarea
            className="field__input field__input--area mono"
            placeholder="✅ Done — describe what you claim is complete…"
            value={claimText}
            onChange={(e) => setClaimText(e.target.value)}
            rows={3}
            disabled={busy}
          />
        </label>

        <button className="judge__submit" type="submit" disabled={busy}>
          {busy ? "Submitting…" : "Submit claim →"}
        </button>

        {state.kind === "ok" ? (
          <p className="judge__result judge__result--ok mono">
            Claim accepted{state.claimId ? ` (${state.claimId})` : ""}. Watch it audit above.
          </p>
        ) : null}
        {state.kind === "error" ? (
          <p className="judge__result judge__result--err mono">{state.message}</p>
        ) : null}
      </form>
    </section>
  );
}

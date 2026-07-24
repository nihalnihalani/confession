import { useEffect, useState } from "react";
import { apiFetch, errorMessage, useAccessKey } from "../api";
import type { SubmitClaimBody, TaskOption } from "../types";

type SubmitState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "ok"; claimId: string; jobId?: string }
  | { kind: "error"; message: string };

export function JudgeSubmit({ tasks }: { tasks: TaskOption[] }): JSX.Element {
  const accessKey = useAccessKey();
  const [taskId, setTaskId] = useState("");
  const [claimText, setClaimText] = useState("");
  const [state, setState] = useState<SubmitState>({ kind: "idle" });

  useEffect(() => {
    if (!taskId && tasks[0]) setTaskId(tasks[0].id);
  }, [taskId, tasks]);

  const submit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    const trimmedTask = taskId.trim();
    const trimmedClaim = claimText.trim();
    if (!trimmedTask || !trimmedClaim) {
      setState({ kind: "error", message: "Task and claim text are both required." });
      return;
    }

    const payload: SubmitClaimBody = {
      agent_id: "judge",
      task_id: trimmedTask,
      claim_text: trimmedClaim,
    };
    setState({ kind: "submitting" });
    try {
      const response = await apiFetch(
        "/api/claims",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        { mutation: true },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { claim_id: string; job_id?: string };
      setState({ kind: "ok", claimId: body.claim_id, jobId: body.job_id });
      setClaimText("");
    } catch (caught) {
      setState({
        kind: "error",
        message: caught instanceof Error ? caught.message : "Claim submission failed.",
      });
    }
  };

  const busy = state.kind === "submitting";

  return (
    <section className="judge panel" aria-label="Judge-submit claim">
      <div className="judge__pitch">
        <div className="judge__heading">
          <span className="section-index mono">03</span>
          <div>
            <span className="eyebrow">Public proof path</span>
            <h2 className="judge__title">Put a claim under oath.</h2>
          </div>
        </div>
        <p className="judge__sub">
          Your claim enters the exact Replay audit path used for Builder work—without
          changing Builder grants or contaminating Pioneer training data.
        </p>
        <div className={`judge__access ${accessKey ? "judge__access--ready" : ""}`}>
          <span aria-hidden="true">{accessKey ? "✓" : "!"}</span>
          <p>
            <strong>{accessKey ? "Access attached" : "Access required"}</strong>
            <small>
              {accessKey
                ? "The claim can enter evidence."
                : "Verify a judge or operator key above."}
            </small>
          </p>
        </div>
      </div>

      <form className="judge__form" onSubmit={(event) => void submit(event)}>
        <label className="field judge__task">
          <span className="field__label">
            <span className="field__step mono">01</span>
            Task under oath
          </span>
          {tasks.length > 0 ? (
            <select
              className="field__input mono"
              value={taskId}
              onChange={(event) => setTaskId(event.target.value)}
              disabled={busy}
            >
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.id} · {task.title}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="field__input mono"
              type="text"
              placeholder="task id"
              value={taskId}
              onChange={(event) => setTaskId(event.target.value)}
              disabled={busy}
            />
          )}
        </label>

        <label className="field field--claim">
          <span className="field__label">
            <span className="field__step mono">02</span>
            Completion claim
            <span className="field__count mono">{claimText.length}/2000</span>
          </span>
          <textarea
            className="field__input field__input--area mono"
            placeholder="State exactly what is complete and ready for Replay to verify."
            value={claimText}
            maxLength={2000}
            onChange={(event) => {
              setClaimText(event.target.value);
              if (state.kind === "error") setState({ kind: "idle" });
            }}
            rows={4}
            disabled={busy}
          />
        </label>

        <button
          className="button button--danger judge__submit"
          type="submit"
          disabled={busy || !accessKey}
        >
          <span>{busy ? "Entering evidence…" : "Submit for audit"}</span>
          <span aria-hidden="true">{busy ? "…" : "↗"}</span>
        </button>

        {state.kind === "ok" ? (
          <p className="form-note form-note--good mono" aria-live="polite">
            Claim {shortId(state.claimId)} accepted
            {state.jobId ? ` · job ${shortId(state.jobId)}` : ""}. Follow the live feed.
          </p>
        ) : null}
        {state.kind === "error" ? (
          <p className="form-note form-note--error mono" role="alert">
            {state.message}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function shortId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}

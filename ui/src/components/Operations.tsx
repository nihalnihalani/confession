import { useEffect, useState } from "react";
import { apiFetch, errorMessage, useAccessKey } from "../api";
import type { JobData, TaskOption } from "../types";

const TERMINAL = new Set(["succeeded", "failed", "interrupted"]);

export function Operations({ tasks }: { tasks: TaskOption[] }): JSX.Element {
  const accessKey = useAccessKey();
  const [taskId, setTaskId] = useState("");
  const [baseModel, setBaseModel] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId && tasks[0]) setTaskId(tasks[0].id);
  }, [taskId, tasks]);

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const response = await apiFetch(`/api/jobs/${jobId}`);
        if (!response.ok) throw new Error(await errorMessage(response));
        const body = (await response.json()) as JobData;
        if (active) {
          setJob(body);
          if (TERMINAL.has(body.status) && timer !== undefined) {
            window.clearInterval(timer);
          }
        }
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not read job status.");
        }
      }
    };
    void load();
    timer = window.setInterval(() => void load(), 1_500);
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [jobId]);

  const start = async (kind: "builder" | "training"): Promise<void> => {
    setError(null);
    setJob(null);
    try {
      const path = kind === "builder" ? "/api/builder/run" : "/api/training/run";
      const body =
        kind === "builder"
          ? { task_id: taskId || null }
          : { base_model: baseModel.trim() || null };
      const response = await apiFetch(
        path,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
        { mutation: true },
      );
      if (!response.ok) throw new Error(await errorMessage(response));
      const accepted = (await response.json()) as { job_id: string };
      setJobId(accepted.job_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Operation could not start.");
    }
  };

  return (
    <section className="panel operations" aria-label="Autonomous operations">
      <header className="panel__head">
        <div>
          <span className="eyebrow">Operator</span>
          <h2 className="panel__title">Run the loop</h2>
        </div>
        <span className="status-word">{accessKey ? "key present" : "locked"}</span>
      </header>

      <div className="operations__block">
        <label className="field">
          <span className="field__label">Builder task</span>
          <select
            className="field__input mono"
            value={taskId}
            onChange={(event) => setTaskId(event.target.value)}
            disabled={tasks.length === 0}
          >
            {tasks.length === 0 ? <option value="">No tasks available</option> : null}
            {tasks.map((task) => (
              <option key={task.id} value={task.id}>
                {task.id} · {task.title}
              </option>
            ))}
          </select>
        </label>
        <button
          className="button button--primary"
          type="button"
          disabled={!accessKey || !taskId}
          onClick={() => void start("builder")}
        >
          Run Builder
        </button>
      </div>

      <div className="operations__block operations__block--training">
        <label className="field">
          <span className="field__label">Pioneer base model</span>
          <input
            className="field__input mono"
            value={baseModel}
            onChange={(event) => setBaseModel(event.target.value)}
            placeholder="use configured model"
          />
        </label>
        <button
          className="button button--quiet"
          type="button"
          disabled={!accessKey}
          onClick={() => void start("training")}
        >
          Start training
        </button>
      </div>

      {jobId ? (
        <div className="job mono" aria-live="polite">
          <span className={`job__state job__state--${job?.status ?? "queued"}`}>
            {job?.status ?? "queued"}
          </span>
          <span className="job__id">{jobId}</span>
          {job?.error ? <span className="job__error">{job.error}</span> : null}
        </div>
      ) : null}
      {error ? (
        <p className="form-note form-note--error mono" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

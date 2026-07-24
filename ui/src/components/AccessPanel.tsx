import { useState } from "react";
import { apiFetch, errorMessage, setAccessKey, useAccessKey } from "../api";

type CheckState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "valid"; role: string }
  | { kind: "error"; message: string };

export function AccessPanel(): JSX.Element {
  const saved = useAccessKey();
  const [value, setValue] = useState(saved);
  const [state, setState] = useState<CheckState>({ kind: "idle" });

  const verify = async (): Promise<void> => {
    setAccessKey(value);
    setState({ kind: "checking" });
    try {
      const response = await apiFetch("/api/auth/check", { method: "POST" });
      if (!response.ok) throw new Error(await errorMessage(response));
      const body = (await response.json()) as { role?: string };
      setState({ kind: "valid", role: body.role ?? "authorized" });
    } catch (error) {
      setAccessKey("");
      setState({
        kind: "error",
        message: error instanceof Error ? error.message : "Access check failed.",
      });
    }
  };

  const clear = (): void => {
    setValue("");
    setAccessKey("");
    setState({ kind: "idle" });
  };

  return (
    <section className="access" aria-label="Mutation access">
      <div className="access__copy">
        <span className="eyebrow">Mutation access</span>
        <span className="access__state">
          {state.kind === "valid"
            ? `${state.role} key verified`
            : saved
              ? "key stored for this tab"
              : "read-only session"}
        </span>
      </div>
      <div className="access__controls">
        <label className="sr-only" htmlFor="access-key">
          CONFESSION access key
        </label>
        <input
          id="access-key"
          className="access__input mono"
          type="password"
          autoComplete="off"
          placeholder="paste access key"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button
          className="button button--quiet"
          type="button"
          disabled={!value.trim() || state.kind === "checking"}
          onClick={() => void verify()}
        >
          {state.kind === "checking" ? "Checking…" : "Verify"}
        </button>
        {saved ? (
          <button className="access__clear" type="button" onClick={clear}>
            Clear
          </button>
        ) : null}
      </div>
      {state.kind === "error" ? (
        <p className="form-note form-note--error mono" role="alert">
          {state.message}
        </p>
      ) : null}
    </section>
  );
}

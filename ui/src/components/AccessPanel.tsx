import { useId, useState } from "react";
import { apiFetch, errorMessage, setAccessKey, useAccessKey } from "../api";

type CheckState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "valid"; role: string }
  | { kind: "error"; message: string };

export function AccessPanel(): JSX.Element {
  const noteId = useId();
  const saved = useAccessKey();
  const [value, setValue] = useState(saved);
  const [visible, setVisible] = useState(false);
  const [state, setState] = useState<CheckState>({ kind: "idle" });

  const verify = async (event?: React.FormEvent): Promise<void> => {
    event?.preventDefault();
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
    setVisible(false);
    setState({ kind: "idle" });
  };

  return (
    <section className="access" aria-label="Mutation access">
      <div className="access__indicator" aria-hidden="true">
        <span className={saved ? "access__key access__key--active" : "access__key"}>
          {saved ? "✓" : "×"}
        </span>
      </div>
      <div className="access__copy">
        <span className="eyebrow">Mutation access</span>
        <strong className="access__state">
          {state.kind === "valid"
            ? `${state.role} access verified`
            : saved
              ? "Access key attached"
              : "Read-only session"}
        </strong>
        <span className="access__note" id={noteId}>
          Keys stay in this browser tab and are never bundled into the dashboard.
        </span>
      </div>
      <form className="access__controls" onSubmit={(event) => void verify(event)}>
        <div className="access__field">
          <label className="sr-only" htmlFor="access-key">
            CONFESSION access key
          </label>
          <input
            id="access-key"
            className="access__input mono"
            type={visible ? "text" : "password"}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-describedby={noteId}
            placeholder="Paste a role-scoped access key"
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              if (state.kind === "error") setState({ kind: "idle" });
            }}
          />
          <button
            className="access__reveal mono"
            type="button"
            onClick={() => setVisible((current) => !current)}
            aria-label={visible ? "Hide access key" : "Show access key"}
          >
            {visible ? "Hide" : "Show"}
          </button>
        </div>
        <button
          className="button button--quiet"
          type="submit"
          disabled={!value.trim() || state.kind === "checking"}
        >
          {state.kind === "checking" ? "Checking…" : "Verify key"}
        </button>
        {saved ? (
          <button className="access__clear mono" type="button" onClick={clear}>
            Clear
          </button>
        ) : null}
      </form>
      {state.kind === "error" ? (
        <p className="form-note form-note--error mono" role="alert">
          {state.message}
        </p>
      ) : null}
      {state.kind === "valid" ? (
        <p className="form-note form-note--good mono" aria-live="polite">
          Verified. Operator controls now use this role.
        </p>
      ) : null}
    </section>
  );
}

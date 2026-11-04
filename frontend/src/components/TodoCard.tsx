import { useState } from "react";
import type { Todo, TodoState } from "../api/types";
import { splitByState, todoMeta } from "../utils/todos";

type Props = {
  todos: Todo[];
  onSetState: (claimId: string, state: TodoState) => void;
  onOpenMemory: (claimId: string) => void;
  loading: boolean;
  error: string | null;
};

/** Promises you made and things you were asked to do, from your own memories. Tick one off or dismiss it. */
export function TodoCard({ todos, onSetState, onOpenMemory, loading, error }: Props) {
  const [tab, setTab] = useState<"open" | "done">("open");
  const { open, done } = splitByState(todos);
  const shown = tab === "open" ? open : done;

  return (
    <section className="card todo-card" aria-label="To-dos">
      <div className="todo-head">
        <h3>To-dos</h3>
        <div className="seg" role="group" aria-label="Show">
          <button type="button" aria-pressed={tab === "open"} onClick={() => setTab("open")}>Open {open.length}</button>
          <button type="button" aria-pressed={tab === "done"} onClick={() => setTab("done")}>Done {done.length}</button>
        </div>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}
      {loading && todos.length === 0 && !error && <p className="muted small" role="status">Looking for promises and requests…</p>}
      {!loading && shown.length === 0 && !error && (
        <p className="muted small">
          {tab === "open"
            ? todos.length === 0 ? "No promises or requests found in your memories." : "Nothing left to do."
            : "Nothing is marked done yet."}
        </p>
      )}

      <ul className="todo-list">
        {shown.map((t) => (
          <li key={t.claim_id} className={`todo ${t.state}`}>
            <button type="button" className="todo-box" aria-pressed={t.state === "done"}
                    aria-label={`${t.state === "done" ? "Mark as not done" : "Mark as done"}: ${t.text}`}
                    onClick={() => onSetState(t.claim_id, t.state === "done" ? "open" : "done")}>
              <span aria-hidden="true">{t.state === "done" ? "✓" : ""}</span>
            </button>
            <div className="todo-main">
              <p className="todo-text" title={t.text}>{t.text}</p>
              <p className="small muted todo-meta">{todoMeta(t)}</p>
              <button type="button" className="todo-source" onClick={() => onOpenMemory(t.claim_id)}
                      aria-label={`Show the memory behind: ${t.text}`}>See the memory</button>
            </div>
            {t.state === "open" && (
              <button type="button" className="icon-btn todo-dismiss" aria-label={`Dismiss: ${t.text}`} title="Dismiss"
                      onClick={() => onSetState(t.claim_id, "dismissed")}>✕</button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

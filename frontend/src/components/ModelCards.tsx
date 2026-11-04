import type { ModelRow, UsageSummary } from "../api/types";
import { modelRows } from "../utils/insights";

type Props = {
  usage: UsageSummary;
  /** The memory day the dashboard is showing, if any. */
  day: string | null;
  /** A demo profile answers from recorded replies rather than live models. */
  demo?: boolean;
};

const num = (n: number) => n.toLocaleString("en-US");

function ModelCard({ row, max }: { row: ModelRow; max: number }) {
  const share = max > 0 ? Math.min(100, Math.max(0, (row.calls / max) * 100)) : 0;
  const rows = modelRows(row);
  return (
    <li className="model-card">
      <div className="model-head">
        <b className="model-name">{row.model}</b>
        <span className="chip accent">{row.kind_label.toLowerCase()}</span>
      </div>
      <div className="model-big"><b>{num(row.calls)}</b> <span className="muted">{row.calls === 1 ? "call" : "calls"}</span></div>
      <div className="model-bar" role="presentation"><span style={{ inlineSize: `${share}%` }} /></div>
      {rows.length > 0 && (
        <dl className="model-kv">
          {rows.map((r) => (
            <div key={r.label}><dt>{r.label}</dt><dd>{r.value}</dd></div>
          ))}
        </dl>
      )}
    </li>
  );
}

/** What the models were asked to do: totals, this day's share and one card per model. */
export function ModelCards({ usage, day, demo = false }: Props) {
  if (!usage.recorded) {
    return (
      <div className="model-empty">
        <p className="muted">No model calls recorded yet</p>
        {demo && <p className="muted">Built from recorded replies</p>}
      </div>
    );
  }
  const max = Math.max(0, ...usage.models.map((m) => m.calls));
  const total = usage.total;
  return (
    <div className="models">
      <p className="model-summary muted">
        {num(total.calls)} {total.calls === 1 ? "call" : "calls"} in all
        {usage.since ? ` since ${usage.since.slice(0, 10)}` : ""}
        {total.cache > 0 ? `, ${num(total.cache)} replayed with no model call` : ""}
        {total.failed > 0 ? `, ${num(total.failed)} failed` : ""}
        {day ? (usage.day
          ? `. On ${day}: ${num(usage.day.calls)} ${usage.day.calls === 1 ? "call" : "calls"}`
          : `. No model calls were about ${day}`) : ""}
      </p>
      {demo && <p className="muted">Built from recorded replies</p>}
      <ul className="model-grid">
        {usage.models.map((m) => <ModelCard key={m.model} row={m} max={max} />)}
      </ul>
    </div>
  );
}

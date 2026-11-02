import type { Graph } from "../api/types";
import { factRows } from "../utils/graph";

type Props = { view: Graph; selectedClaim: string | null; onSelect: (claimId: string) => void };

/** The graph as a table: the keyboard and screen-reader route to every fact in the picture. */
export function FactsTable({ view, selectedClaim, onSelect }: Props) {
  const rows = factRows(view);
  return (
    <details className="card facts">
      <summary>All facts as a table ({rows.length})</summary>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Every remembered fact, with how it is known and where it came from</caption>
          <thead>
            <tr><th scope="col">Time</th><th scope="col">Fact</th><th scope="col">Known by</th><th scope="col">Status</th><th scope="col">From</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.status === "superseded" ? "replaced" : undefined} aria-selected={r.id === selectedClaim}>
                <td>{r.when}</td>
                <td>
                  <button type="button" onClick={() => onSelect(r.id)}>
                    {r.subject} {r.relation} {r.object}
                  </button>
                </td>
                <td>{r.evidence}</td>
                <td>{r.status === "superseded" ? "Replaced" : r.status === "disputed" ? "Disputed" : "Current"}</td>
                <td>{r.sources}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="muted">No facts yet. Play the day to build the graph.</td></tr>}
          </tbody>
        </table>
      </div>
    </details>
  );
}

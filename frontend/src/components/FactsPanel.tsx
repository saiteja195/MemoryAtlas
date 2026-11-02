import { useMemo, useState } from "react";
import type { Graph } from "../api/types";
import { CATEGORY_INFO, factRows, groupFacts, type FactCategory } from "../utils/graph";

type Props = { view: Graph; selectedClaim: string | null; onSelect: (claimId: string) => void };

const ICON: Record<FactCategory, string> = { people: "👥", places: "📍", details: "🏷", inferred: "✨" };

/** Every remembered fact as a readable list, grouped by what it is about. */
export function FactsPanel({ view, selectedClaim, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [currentOnly, setCurrentOnly] = useState(false);
  const rows = useMemo(() => factRows(view), [view]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) =>
      (!currentOnly || r.status !== "superseded")
      && (!q || `${r.subject} ${r.relation} ${r.object}`.toLowerCase().includes(q)));
  }, [rows, query, currentOnly]);
  const groups = groupFacts(shown);

  return (
    <div className="facts-panel">
      <div className="facts-tools">
        <label className="sr-only" htmlFor="fact-search">Search facts</label>
        <input id="fact-search" type="search" placeholder="Search facts…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="check"><input type="checkbox" checked={currentOnly} onChange={(e) => setCurrentOnly(e.target.checked)} /> Current only</label>
      </div>
      <p className="small muted">
        {rows.length === 0 ? "No facts yet. Play the day to build the memory."
          : `${shown.length} of ${rows.length} facts. Select one to see it on the map and where it came from.`}
      </p>
      {groups.map((g) => (
        <details key={g.category} className="fact-group" open>
          <summary>
            <span aria-hidden="true">{ICON[g.category]}</span>
            <span className="fg-title">{CATEGORY_INFO[g.category].title}</span>
            <span className="chip">{g.rows.length}</span>
          </summary>
          <p className="small muted fg-hint">{CATEGORY_INFO[g.category].hint}</p>
          <ul className="fact-list">
            {g.rows.map((r) => (
              <li key={r.id}>
                <button type="button" className={`fact-row ${r.status === "superseded" ? "replaced" : ""}`}
                        aria-current={r.id === selectedClaim ? "true" : undefined} onClick={() => onSelect(r.id)}>
                  <span className="fact-sentence">
                    <b>{r.subject}</b> <span className="rel">{r.relation}</span> <b>{r.object}</b>
                  </span>
                  <span className="fact-meta">
                    {r.when && <span>{r.when}</span>}
                    <span>{r.sources || "—"}</span>
                    {r.status === "superseded" && <span className="chip">⏱ Replaced</span>}
                    {r.status === "disputed" && <span className="chip warn">⚠ Disputed</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      ))}
      {rows.length > 0 && groups.length === 0 && <p className="muted">Nothing matches “{query}”.</p>}
    </div>
  );
}

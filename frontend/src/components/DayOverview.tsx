import type { GraphNode } from "../api/types";
import type { DayCard } from "../utils/graph";

type Props = {
  cards: DayCard[];
  selectedId: string | null;
  onSelect: (episodeId: string) => void;
  onOpenInMap: (episodeId: string) => void;
};

const GLYPH: Record<string, string> = { person: "👤", place: "📍", object: "◆", org: "🏢", item: "🏷" };

function Chips({ nodes, label }: { nodes: GraphNode[]; label: string }) {
  if (nodes.length === 0) return null;
  return (
    <li className="chip-row">
      <span className="chip-label">{label}</span>
      {nodes.map((n) => (
        <span key={n.id} className={`entity-chip t-${n.type}`}>
          <span aria-hidden="true">{GLYPH[n.type] ?? "•"}</span>{n.name}
        </span>
      ))}
    </li>
  );
}

/** The day as a vertical list of moments. Plain words first; the graph is one click away. */
export function DayOverview({ cards, selectedId, onSelect, onOpenInMap }: Props) {
  return (
    <div className="day">
      <div className="day-intro">
        <h2>Your day, as moments</h2>
        <p>
          MemoryAtlas groups what it saw into <strong>moments</strong>: things that happened around the same
          time and place. Each card lists who and what was there. Open one in the map to see how it all connects.
        </p>
      </div>
      <ol className="moments" aria-label="Moments of the day">
        {cards.map((c) => (
          <li key={c.id} className={`moment ${selectedId === c.id ? "selected" : ""}`}>
            <time className="moment-time">{c.time}</time>
            <div className="moment-card">
              <button type="button" className="moment-main" aria-pressed={selectedId === c.id} onClick={() => onSelect(c.id)}>
                <strong>{c.title}</strong>
                {c.summary && <span className="moment-summary">{c.summary}</span>}
              </button>
              <ul className="moment-meta">
                <Chips nodes={c.people} label="People" />
                <Chips nodes={c.places} label="Places" />
                <Chips nodes={c.things} label="Things" />
              </ul>
              <div className="moment-foot">
                <span className="muted small">
                  {c.facts} {c.facts === 1 ? "fact" : "facts"}{c.sources.length ? ` · from ${c.sources.join(", ").toLowerCase()}` : ""}
                </span>
                <button type="button" className="btn small" onClick={() => onOpenInMap(c.id)}>Open in map</button>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

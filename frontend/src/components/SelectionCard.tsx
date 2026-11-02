import type { Graph } from "../api/types";
import {
  clock, episodeMembers, episodeTimeLabel, factRows, humanPredicate, OWNER_ID, type Selection,
} from "../utils/graph";
import { EvidenceChip, SourceChips, StatusChip } from "./Badges";

type Props = {
  full: Graph;
  view: Graph;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onWhy: (claimIds: string[]) => void;
  onOpenEpisode: (episodeId: string) => void;
};

export function SelectionCard({ full, view, selection, onSelect, onWhy, onOpenEpisode }: Props) {
  if (!selection) {
    return (
      <section className="card selection" aria-label="Selected item">
        <p className="muted">Click a person, place or fact in the graph, or an answer's source, to see where it came from.</p>
      </section>
    );
  }

  if (selection.kind === "claim") {
    const e = view.edges.find((x) => x.id === selection.id) ?? full.edges.find((x) => x.id === selection.id);
    if (!e) return <section className="card selection"><p className="muted">That fact is no longer in the memory.</p></section>;
    const replacedBy = e.superseded_by ? full.edges.find((x) => x.id === e.superseded_by) : undefined;
    return (
      <section className="card selection" aria-label="Selected fact">
        <p className="claim-text">{e.text}</p>
        <div className="row">
          <EvidenceChip evidence={e.evidence_type} />
          <StatusChip status={e.status} />
          <span className="chip">{Math.round(e.confidence * 100)}% sure</span>
          {e.event_time && <span className="chip">at {clock(e.event_time)}</span>}
        </div>
        <div className="row small"><span className="muted">Supported by</span><SourceChips supports={e.support} /></div>
        {replacedBy && (
          <p className="small muted">
            Replaced by: <button type="button" className="btn small ghost" onClick={() => onSelect({ kind: "claim", id: replacedBy.id })}>{replacedBy.text}</button>
          </p>
        )}
        <div className="row">
          <button type="button" className="btn primary small" onClick={() => onWhy([e.id])}>Why do we believe this?</button>
        </div>
      </section>
    );
  }

  if (selection.kind === "entity") {
    const node = full.nodes.find((n) => n.id === selection.id);
    const rows = factRows({ nodes: view.nodes, edges: view.edges.filter((e) => e.source === selection.id || e.target === selection.id) });
    return (
      <section className="card selection" aria-label="Selected item">
        <p className="claim-text">{node?.name ?? selection.id} <span className="chip">{node?.type}</span></p>
        {rows.length === 0 ? <p className="muted">Nothing is remembered about this yet.</p> : (
          <ul className="facts-list">
            {rows.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => onSelect({ kind: "claim", id: r.id })}>
                  <span className="muted">{r.when}</span>
                  <span>{r.subject} {r.relation} {r.object}</span>
                  {r.status === "superseded" && <span className="chip">⏱ replaced</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  const ep = full.nodes.find((n) => n.id === selection.id);
  const members = (episodeMembers(view).get(selection.id) ?? []).filter((m) => m.id !== OWNER_ID);
  const summary = view.edges.find((e) => e.predicate === "summary_of" && e.source === selection.id && e.status !== "superseded");
  return (
    <section className="card selection" aria-label="Selected episode">
      <p className="claim-text">Episode {ep ? episodeTimeLabel(ep) : ""}</p>
      <p className="small muted">{members.length ? `With ${members.map((m) => m.name).join(", ")}` : "Just you"}</p>
      {summary?.value && <p>{summary.value}</p>}
      <div className="row">
        <button type="button" className="btn primary small" onClick={() => onOpenEpisode(selection.id)}>Open this episode</button>
        {summary && <button type="button" className="btn small" onClick={() => onWhy([summary.id])}>Why this summary?</button>}
      </div>
      <p className="small muted">{humanPredicate("summary_of")} is written from the facts below it and disappears with them.</p>
    </section>
  );
}


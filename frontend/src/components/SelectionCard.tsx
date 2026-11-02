import type { Graph } from "../api/types";
import {
  clock, episodeMembers, episodeTimeLabel, factRows, humanPredicate, OWNER_ID, type Selection,
} from "../utils/graph";
import { EvidenceChip, SourceChips, StatusChip } from "./Badges";
import { CorrectClaim, type CorrectionBody } from "./CorrectClaim";

type Props = {
  full: Graph;
  view: Graph;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onWhy: (claimIds: string[]) => void;
  onCorrect: (claimId: string, body: CorrectionBody) => Promise<boolean>;
  replay: boolean;
  onOpenEpisode: (episodeId: string) => void;
  onClose: () => void;
};

const TYPE_WORD: Record<string, string> = { person: "Person", place: "Place", object: "Thing", org: "Organisation", item: "Item" };

export function SelectionCard({ full, view, selection, onSelect, onWhy, onCorrect, replay, onOpenEpisode, onClose }: Props) {
  if (!selection) return null;
  const close = <button type="button" className="btn small ghost close" onClick={onClose} aria-label="Close details">✕</button>;

  if (selection.kind === "claim") {
    const e = view.edges.find((x) => x.id === selection.id) ?? full.edges.find((x) => x.id === selection.id);
    if (!e) return <section className="inspector">{close}<p className="muted">That fact is no longer in the memory.</p></section>;
    const replacedBy = e.superseded_by ? full.edges.find((x) => x.id === e.superseded_by) : undefined;
    return (
      <section className="inspector" aria-label="Selected fact">{close}
        <p className="eyebrow">Fact</p>
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
        {(e.status === "active" || e.status === "disputed") && e.predicate !== "part_of_episode" && (
          <CorrectClaim key={e.id} claimText={e.text} replay={replay} onSubmit={(body) => onCorrect(e.id, body)} />
        )}
      </section>
    );
  }

  if (selection.kind === "entity") {
    const node = full.nodes.find((n) => n.id === selection.id);
    const rows = factRows({ nodes: view.nodes, edges: view.edges.filter((e) => e.source === selection.id || e.target === selection.id) });
    return (
      <section className="inspector" aria-label="Selected item">{close}
        <p className="eyebrow">{TYPE_WORD[node?.type ?? ""] ?? "Item"}</p>
        <p className="claim-text">{node?.name ?? selection.id}</p>
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
    <section className="inspector" aria-label="Selected moment">{close}
      <p className="eyebrow">Moment</p>
      <p className="claim-text">{ep ? episodeTimeLabel(ep) : ""}</p>
      <p className="small muted">{members.length ? `With ${members.map((m) => m.name).join(", ")}` : "Just you"}</p>
      {summary?.value && <p>{summary.value}</p>}
      <div className="row">
        <button type="button" className="btn primary small" onClick={() => onOpenEpisode(selection.id)}>Open in map</button>
        {summary && <button type="button" className="btn small" onClick={() => onWhy([summary.id])}>Why this summary?</button>}
      </div>
      <p className="small muted">{humanPredicate("summary_of")} is written from the facts below it and disappears with them.</p>
    </section>
  );
}


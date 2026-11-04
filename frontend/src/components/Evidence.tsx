import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Provenance } from "../api/types";
import { clock, ruleLabel, sourceLabel } from "../utils/graph";
import { Dialog } from "./Dialog";
import { EvidenceChip } from "./Badges";

type Props = {
  claimIds: string[] | null; onClose: () => void;
  /** The person asks to delete the saved memory a fact rests on. */
  onDelete?: (source: { id: string; kind: string; text: string }) => void;
};

/**
 * "Why do we believe this?" A non-modal panel, so the graph stays visible and clickable while it
 * is open. Each claim is traced down to the captured sources it rests on.
 */
export function EvidenceDrawer({ claimIds, onClose, onDelete }: Props) {
  const [trees, setTrees] = useState<Provenance[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!claimIds) return;
    let cancelled = false;
    setTrees(null);
    setError(null);
    Promise.all(claimIds.map((id) => api.provenance(id)))
      .then((t) => { if (!cancelled) setTrees(t); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); });
    return () => { cancelled = true; };
  }, [claimIds]);

  return (
    <Dialog open={claimIds !== null} onClose={onClose} title="Why do we believe this?" modal={false} className="drawer">
      {error && <p className="notice error" role="alert">{error}</p>}
      {!trees && !error && <progress aria-label="Loading the evidence" />}
      {trees?.map((t) => <div className="prov" key={t.claim_id}><Node node={t} top onDelete={onDelete} /></div>)}
      {trees && <p className="small muted">Each fact is traced to what was actually captured. If a source is withdrawn, everything that rested only on it disappears.</p>}
    </Dialog>
  );
}

function Node({ node, top, onDelete }: { node: Provenance; top?: boolean; onDelete?: Props["onDelete"] }) {
  return (
    <div>
      <div className="prov-claim">
        {top ? <h3>{node.text}</h3> : <strong>{node.text}</strong>}
        <EvidenceChip evidence={node.evidence} />
        <span className="chip">{Math.round(node.confidence * 100)}%</span>
      </div>
      <ul>
        {node.justifications.map((j, i) =>
          j.kind === "source" ? (
            <li key={i} className="prov-source">
              <span><span className="chip accent">{sourceLabel(j.source.kind)}</span> <span className="muted">{clock(j.source.captured_at)}</span></span>
              <q>{j.source.text}</q>
              {onDelete && (
                <button type="button" className="link-btn danger-text" onClick={() => onDelete({ id: j.source.source_id, kind: j.source.kind, text: j.source.text })}>
                  Delete this memory
                </button>
              )}
            </li>
          ) : (
            <li key={i} className="prov-derivation">
              <div className="prov-claim"><span className="chip warn">Inferred</span><span>{ruleLabel(j.rule)}, from:</span></div>
              <ul>{(j.premises ?? []).map((p) => <li key={p.claim_id}><Node node={p} onDelete={onDelete} /></li>)}</ul>
            </li>
          ),
        )}
        {node.justifications.length === 0 && <li className="muted small">No supporting source is available any more.</li>}
      </ul>
    </div>
  );
}

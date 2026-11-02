import type { Grant } from "../api/types";
import { personName, sessionLabel } from "./Badges";

type Props = {
  grants: Grant[];
  onSimulate: (grantId: string) => void;
  onReceipt: (receiptId: string) => void;
};

export function ConsentPanel({ grants, onSimulate, onReceipt }: Props) {
  return (
    <>
      <p className="small muted">
        Everyone in a recording has to agree to it. If one person withdraws, MemoryAtlas removes every memory that rested
        only on that agreement and keeps the ones other sources still support.
      </p>
      {grants.length === 0 && <p className="muted small">No consent has been given yet. Play the day to start.</p>}
      <ul style={{ display: "grid", gap: 10 }}>
        {grants.map((g) => (
          <li key={g.grant_id} className={`card grant ${g.revoked_at ? "withdrawn" : ""}`}>
            <div className="top">
              <span className="who">{personName(g.grantor)}</span>
              <span className="muted small">{sessionLabel(g.scope_ref)}</span>
              {g.revoked_at ? <span className="chip bad" style={{ marginInlineStart: "auto" }}>Withdrawn</span>
                            : <span className="chip ok" style={{ marginInlineStart: "auto" }}>Active</span>}
            </div>
            <div className="actions">
              {g.revoked_at ? (
                g.receipt_id && <button type="button" className="btn small" onClick={() => onReceipt(g.receipt_id!)}>View the forgetting receipt</button>
              ) : (
                <>
                  <button type="button" className="btn small danger" onClick={() => onSimulate(g.grant_id)}>
                    {g.grantor === "me" ? "Withdraw my consent…" : `${personName(g.grantor)} withdraws…`}
                  </button>
                  <a className="btn small" href={`?as=device&grant=${encodeURIComponent(g.grant_id)}`} target="_blank" rel="noopener">
                    Open on {g.grantor === "me" ? "my" : `${personName(g.grantor)}'s`} phone (new tab)
                  </a>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

import type { Grant } from "../api/types";
import { personName, sessionLabel } from "./Badges";

type Props = {
  grants: Grant[];
  onSimulate: (grantId: string) => void;
  /** The owner withdraws their own consent (no code needed). */
  onWithdraw: (grantId: string) => void;
  onExpire: (grantId: string) => void;
  onReceipt: (receiptId: string) => void;
  /** What the app is busy doing, when it is ("Letting the consent expire"). */
  busy?: string | null;
};

/** "until 3:30 PM", or "until 3:30 PM tomorrow" when it is not today. */
function until(iso: string): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? `until ${time}` : `until ${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
}

export function ConsentPanel({ grants, onSimulate, onWithdraw, onExpire, onReceipt, busy }: Props) {
  return (
    <>
      <p className="small muted">
        Everyone in a recording has to agree to it. If one person withdraws, MemoryAtlas removes every memory that rested
        only on that agreement and keeps the ones other sources still support. A consent can also have an end time; when
        it passes, the same removal happens by itself.
      </p>
      {busy && /expire|forget|withdraw/i.test(busy) && (
        <div className="save-progress" role="status" aria-live="polite">
          <strong>{busy}…</strong>
          <span className="small muted">Removing what rested on it, then checking nothing leaks. This can take a minute or two.</span>
        </div>
      )}
      {grants.length === 0 && <p className="muted small">No consent has been given yet. Play the day to start.</p>}
      <ul style={{ display: "grid", gap: 10 }}>
        {grants.map((g) => (
          <li key={g.grant_id} className={`card grant ${g.revoked_at ? "withdrawn" : ""}`}>
            <div className="top">
              <span className="who">{personName(g.grantor)}</span>
              <span className="muted small">{sessionLabel(g.scope_ref)}</span>
              {g.revoked_at ? <span className="chip bad" style={{ marginInlineStart: "auto" }}>{g.ended_reason === "expired" ? "Expired" : "Withdrawn"}</span>
                            : <span className="chip ok" style={{ marginInlineStart: "auto" }}>Active{g.expires_at ? ` · ${until(g.expires_at)}` : ""}</span>}
            </div>
            <div className="actions">
              {g.revoked_at ? (
                g.receipt_id && <button type="button" className="btn small" onClick={() => onReceipt(g.receipt_id!)}>View the forgetting receipt</button>
              ) : (
                <>
                  <button type="button" className="btn small danger" onClick={() => (g.grantor === "me" ? onWithdraw(g.grant_id) : onSimulate(g.grant_id))}>
                    {g.grantor === "me" ? "Withdraw my consent…" : `${personName(g.grantor)} withdraws…`}
                  </button>
                  <button type="button" className="btn small ghost" onClick={() => onExpire(g.grant_id)}
                          title="Demo: skip ahead to the moment this consent runs out">Let it expire now (demo)</button>
                  {g.grantor !== "me" && (
                  <a className="btn small" href={`?as=device&grant=${encodeURIComponent(g.grant_id)}`} target="_blank" rel="noopener">
                    Open on {personName(g.grantor)}'s phone (new tab)
                  </a>
                  )}
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

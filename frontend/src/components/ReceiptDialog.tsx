import type { Receipt } from "../api/types";
import { humanPredicate, ruleLabel, sourceLabel } from "../utils/graph";
import { personName } from "./Badges";
import { Dialog } from "./Dialog";

const MARK = { pass: "✓", fail: "✗", skipped: "–" } as const;
const WORD = { pass: "Passed", fail: "Failed", skipped: "Skipped" } as const;

export function ReceiptDialog({ receipt, onClose }: { receipt: Receipt | null; onClose: () => void }) {
  const r = receipt;
  return (
    <Dialog open={r !== null} onClose={onClose} title="Forgetting receipt" initialFocus="[data-autofocus]"
            footer={<button type="button" className="btn primary" data-autofocus onClick={onClose}>Done</button>}>
      {r && (
        <>
          <p>
            <strong>{personName(r.grantor)}</strong> withdrew consent. Everything that depended only on that permission was removed;
            everything with other support was kept.
          </p>
          <div className="row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span className={`chip ${r.summary.all_passed ? "ok" : r.summary.probes_failed ? "bad" : "warn"}`}>
              {r.summary.probes_passed} of {r.summary.probes_total} checks passed
              {r.summary.probes_failed ? `, ${r.summary.probes_failed} failed` : ""}
              {r.summary.probes_skipped ? `, ${r.summary.probes_skipped} skipped` : ""}
            </span>
          </div>

          <div className="stat-grid">
            <div className="stat"><b>{r.removed.claims_deleted}</b><span className="muted small">facts removed</span></div>
            <div className="stat"><b>{r.removed.sources_blanked}</b><span className="muted small">recordings erased</span></div>
            <div className="stat"><b>{r.kept.claims_surviving}</b><span className="muted small">facts kept</span></div>
            <div className="stat"><b>{r.removed.chat_messages_redacted + r.removed.answer_cache_rows}</b><span className="muted small">cached answers and chat lines cleared</span></div>
          </div>

          <section>
            <h3>What was removed</h3>
            <p className="small muted">
              {Object.entries(r.removed.claims_deleted_by_kind).map(([k, n]) => `${n} × ${humanPredicate(k)}`).join(" · ") || "Nothing."}
            </p>
          </section>

          {r.retained.length > 0 && (
            <section>
              <h3>Kept, because something else still supports it</h3>
              <ul className="kept">
                {r.retained.filter((x) => x.predicate !== "part_of_episode").map((x) => (
                  <li key={x.claim_id}>
                    <div>{x.text}</div>
                    <div className="why">Lost: {x.lost_support.map(pretty).join(", ")}. Still supported by: {x.still_supported_by.map(pretty).join(", ")}.</div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h3>Automated checks</h3>
            <ul>
              {r.probes.map((p) => (
                <li key={p.id} className={`probe ${p.status}`}>
                  <span className="mark" aria-hidden="true">{MARK[p.status]}</span>
                  <span><span className="sr-only">{WORD[p.status]}: </span>{p.name.replace(/^[^:]+:\s*/, "")}</span>
                  <span className="small muted">{detail(p)}</span>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h3>Good to know</h3>
            <ul className="small muted" style={{ display: "grid", gap: 4 }}>{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          </section>
        </>
      )}
    </Dialog>
  );
}

/** "transcript_segment at 12:35" -> "Conversation at 12:35"; "derivation (rule)" -> "Inferred (...)". */
function pretty(s: string): string {
  const at = /^(\w+) at (\d\d:\d\d)$/.exec(s);
  if (at) return `${sourceLabel(at[1])} at ${at[2]}`;
  const d = /^derivation \((.+)\)$/.exec(s);
  return d ? `Inferred: ${ruleLabel(d[1]).toLowerCase()}` : s;
}

function detail(p: Receipt["probes"][number]): string {
  const d = p.detail as Record<string, unknown>;
  if (p.status === "skipped") return String(d.reason ?? "Not run");
  if (p.id === 6) return `${d.questions ?? 0} adversarial questions asked`;
  if (p.id === 2) return `${d.terms ?? 0} phrases searched for`;
  if (p.id === 7) return `${d.media_bytes ?? 0} bytes of media; ${(d.files_scanned as string[] | undefined)?.length ?? 0} database files scanned`;
  return `${d.hits ?? 0} leaks found`;
}

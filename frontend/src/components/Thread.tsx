import type { Answer } from "../api/types";
import { clock } from "../utils/graph";
import { dayChip, type Turn } from "../utils/assistant";
import { PHASES } from "../utils/chat";
import { suggest, type BEFORE_GROUPS } from "../utils/suggest";
import { EvidenceChip } from "./Badges";

const STATUS = {
  answered: { text: "Answered", cls: "ok", mark: "✓" },
  partial: { text: "Partly answered", cls: "warn", mark: "◐" },
  abstained: { text: "No record", cls: "", mark: "∅" },
} as const;

type Groups = typeof BEFORE_GROUPS;

type Props = {
  turns: Turn[];                 // oldest first
  asking: boolean;
  phase: 0 | 1 | 2;
  groups: Groups;
  /** The day on screen: a message about another day says so. */
  selectedDay: string | null;
  onAsk: (q: string) => void;
  onCite: (claimId: string) => void;
  onWhy: (claimIds: string[]) => void;
};

/** The conversation: each question with its answer, and the three working steps while one is pending. */
export function Thread({ turns, asking, phase, groups, selectedDay, onAsk, onCite, onWhy }: Props) {
  return (
    <>
      {turns.map((qa) => {
        const chip = dayChip(qa.asOf, selectedDay);
        return (
          <article className={`qa ${qa.answer?.status ?? ""}`} key={qa.id} aria-label={`Question: ${qa.question}`}>
            <p className="q bubble me">{qa.question}</p>
            {chip && <p className="small muted day-chip">About {chip}</p>}
            {qa.error && qa.error.notRecorded && (
              <NotRecorded question={qa.question} groups={groups} disabled={asking} onAsk={onAsk} />
            )}
            {qa.error && !qa.error.notRecorded && <div className="notice error" role="alert">{qa.error.text}</div>}
            {qa.answer && <Answered a={qa.answer} onCite={onCite} onWhy={onWhy} />}
          </article>
        );
      })}
      {asking && (
        <ol className="steps" role="status" aria-label="Looking through your memories">
          {PHASES.map((label, i) => (
            <li key={label} className={i < phase ? "done" : i === phase ? "now" : ""}>
              <span aria-hidden="true">{i < phase ? "✓" : i === phase ? "…" : "·"}</span> {label}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function Answered({ a, onCite, onWhy }: { a: Answer; onCite: (id: string) => void; onWhy: (ids: string[]) => void }) {
  const s = STATUS[a.status];
  return (
    <div className="bubble bot">
      <div className="row">
        <span className={`chip ${s.cls}`}><span aria-hidden="true">{s.mark}</span> {s.text}</span>
        {a.checks.length > 0 && <span className="chip" title={a.checks.join(" ")}>Checked and corrected</span>}
        {(a.cited_tools ?? []).length > 0 && <span className="chip" title="Worked out from the day's coverage or the models' usage, not from a memory">From your usage figures</span>}
      </div>
      <p className="a">{a.answer}</p>
      {a.uncertainty_note && <p className="small muted">{a.uncertainty_note}</p>}
      {a.citations.length > 0 && (
        <div className="cites">
          <p className="small muted">Based on</p>
          {a.citations.map((c) => (
            <button type="button" className="cite" key={c.claim_id} onClick={() => onCite(c.claim_id)}
                    aria-label={`Show on the graph: ${c.text}`}>
              <span className="t">{c.text}{c.when ? <span className="muted"> · {clock(c.when)}</span> : null}</span>
              <EvidenceChip evidence={c.evidence} />
            </button>
          ))}
          <div className="row">
            <button type="button" className="btn small" onClick={() => onWhy(a.cited_claim_ids)}>Why? Show the evidence</button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Replay mode could not answer. Say why in plain words and put the nearest answerable questions one tap away. */
function NotRecorded({ question, groups, disabled, onAsk }: {
  question: string; groups: typeof BEFORE_GROUPS; disabled: boolean; onAsk: (q: string) => void;
}) {
  const close = suggest(question, groups);
  const fallback = groups[0].prompts.slice(0, 2);
  const options = close.length ? close : fallback;
  return (
    <div className="not-recorded bubble bot" role="status">
      <p><strong>No recording for that question.</strong></p>
      <p className="small muted">
        Replay mode only answers questions that were recorded, and recordings depend on how far the day has played.
        Nothing is wrong with your memory.
      </p>
      <p className="small muted">{close.length ? "Closest questions that do have an answer:" : "Try one of these instead:"}</p>
      <div className="examples">
        {options.map((o) => <button type="button" key={o} disabled={disabled} onClick={() => onAsk(o)}>{o}</button>)}
      </div>
    </div>
  );
}

import { useState, type FormEvent } from "react";
import type { Answer, LlmMode } from "../api/types";
import { clock } from "../utils/graph";
import { EvidenceChip } from "./Badges";
import { AFTER_GROUPS, BEFORE_GROUPS, isKnown, suggest } from "../utils/suggest";

export type QA = {
  id: number;
  question: string;
  answer?: Answer;
  error?: { text: string; notRecorded: boolean };
};

type Props = {
  qas: QA[];
  asking: boolean;
  forgotten: boolean;
  mode: LlmMode | undefined;
  onAsk: (q: string) => void;
  onCite: (claimId: string) => void;
  onWhy: (claimIds: string[]) => void;
};

const STATUS = {
  answered: { text: "Answered", cls: "ok", mark: "✓" },
  partial: { text: "Partly answered", cls: "warn", mark: "◐" },
  abstained: { text: "No record", cls: "", mark: "∅" },
} as const;

export function AskPanel({ qas, asking, forgotten, mode, onAsk, onCite, onWhy }: Props) {
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = q.trim();
    if (text.length >= 3 && !asking) { onAsk(text); setQ(""); }
  };
  const groups = forgotten ? AFTER_GROUPS : BEFORE_GROUPS;
  const replay = mode === "replay";
  const typed = q.trim();
  // In replay mode a free-form question probably has no recording: offer the nearest ones while typing.
  const near = replay && typed.length >= 3 && !isKnown(typed, groups) ? suggest(typed, groups) : [];

  return (
    <>
      <form className="ask-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="question">Ask about your day</label>
        <input id="question" type="text" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off"
               placeholder={replay ? "Pick a question below, or type one…" : "Ask about your day…"} maxLength={500}
               aria-describedby={replay ? "ask-mode-note" : undefined} />
        <button type="submit" className="btn primary" disabled={asking || typed.length < 3}>{asking ? "Thinking…" : "Ask"}</button>
      </form>

      {near.length > 0 && (
        <div className="nearby" role="group" aria-label="Questions with recorded answers">
          <p className="small muted">Closest questions with a recorded answer</p>
          {near.map((n) => (
            <button type="button" key={n} disabled={asking} onClick={() => { setQ(""); onAsk(n); }}>{n}</button>
          ))}
        </div>
      )}

      {replay && (
        <p className="mode-note small" id="ask-mode-note">
          <span className="chip warn">Replay mode</span>
          <span>
            This demo answers a fixed set of questions from recordings, so it works offline. To ask anything, run
            with a live key (<a href="https://github.com/saiteja195/MemoryAtlas/blob/main/docs/LOCAL_SETUP.md#4-model-modes" target="_blank" rel="noopener">how</a>).
          </span>
        </p>
      )}

      <div className="prompt-groups" role="group" aria-label="Example questions">
        {groups.map((g) => (
          <details key={g.title} className="prompt-group" open>
            <summary><strong>{g.title}</strong><span className="muted small">{g.hint}</span></summary>
            <div className="examples">
              {g.prompts.map((ex) => (
                <button type="button" key={ex} disabled={asking} onClick={() => onAsk(ex)}>{ex}</button>
              ))}
            </div>
          </details>
        ))}
      </div>

      <div className="thread" aria-live="off">
        {asking && <progress aria-label="Looking through your memories" />}
        {qas.map((qa) => (
          <article className={`card qa ${qa.answer?.status ?? ""}`} key={qa.id} aria-label={`Question: ${qa.question}`}>
            <p className="q">{qa.question}</p>
            {qa.error && qa.error.notRecorded && (
              <NotRecorded question={qa.question} groups={groups} disabled={asking} onAsk={onAsk} />
            )}
            {qa.error && !qa.error.notRecorded && <div className="notice error" role="alert">{qa.error.text}</div>}
            {qa.answer && <Answered a={qa.answer} onCite={onCite} onWhy={onWhy} />}
          </article>
        ))}
        {qas.length === 0 && !asking && <p className="muted small">Answers appear here, each with the memories it rests on.</p>}
      </div>
    </>
  );
}

function Answered({ a, onCite, onWhy }: { a: Answer; onCite: (id: string) => void; onWhy: (ids: string[]) => void }) {
  const s = STATUS[a.status];
  return (
    <>
      <div className="row">
        <span className={`chip ${s.cls}`}><span aria-hidden="true">{s.mark}</span> {s.text}</span>
        {a.checks.length > 0 && <span className="chip" title={a.checks.join(" ")}>Checked and corrected</span>}
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
    </>
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
    <div className="not-recorded" role="status">
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

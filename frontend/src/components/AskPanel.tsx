import { useState, type FormEvent } from "react";
import type { Answer, LlmMode } from "../api/types";
import { clock } from "../utils/graph";
import { EvidenceChip } from "./Badges";

export type QA = {
  id: number;
  question: string;
  answer?: Answer;
  error?: { text: string; notRecorded: boolean };
};

const BEFORE = [
  "Which restaurant did Alex recommend when we met near the office?",
  "Where is my wallet?",
  "Did I leave my wallet at the café?",
];
const AFTER = [
  "What did Alex promise me?",
  "Which restaurant did Alex recommend when we met near the office?",
  "What colour is the awning at Luna Taqueria?",
  "Did I have a meeting with Alex?",
];

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
  const examples = forgotten ? AFTER : BEFORE;

  return (
    <>
      <form className="ask-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="question">Ask about your day</label>
        <input id="question" type="text" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off"
               placeholder="Ask about your day…" maxLength={500} />
        <button type="submit" className="btn primary" disabled={asking || q.trim().length < 3}>{asking ? "Thinking…" : "Ask"}</button>
      </form>
      <div className="examples" role="group" aria-label="Example questions">
        {examples.map((ex) => (
          <button type="button" key={ex} disabled={asking} onClick={() => onAsk(ex)}>{ex}</button>
        ))}
      </div>
      {mode === "replay" && (
        <p className="small muted">Replay mode answers recorded questions only. The examples above are all recorded.</p>
      )}

      <div className="thread" aria-live="off">
        {asking && <progress aria-label="Looking through your memories" />}
        {qas.map((qa) => (
          <article className={`card qa ${qa.answer?.status ?? ""}`} key={qa.id} aria-label={`Question: ${qa.question}`}>
            <p className="q">{qa.question}</p>
            {qa.error && (
              <div className="notice warn" role="alert">
                {qa.error.notRecorded
                  ? "That question isn't in the recording. In replay mode only recorded questions can be answered: try one of the examples, or run with a live key."
                  : qa.error.text}
              </div>
            )}
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

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Answer, LlmMode } from "../api/types";
import { clock } from "../utils/graph";
import { followUps, oldestFirst, PHASES, phaseAt } from "../utils/chat";
import { prefersReducedMotion } from "../utils/theme";
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
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const thread = useRef<HTMLDivElement>(null);

  const groups = forgotten ? AFTER_GROUPS : BEFORE_GROUPS;
  const replay = mode === "replay";
  const turns = oldestFirst(qas);
  const typed = q.trim();
  // In replay mode a free-form question probably has no recording: offer the nearest ones while typing.
  const near = replay && typed.length >= 3 && !isKnown(typed, groups) ? suggest(typed, groups) : [];
  const last = qas[0];
  const next = !asking && last?.answer ? followUps(qas.map((x) => x.question), groups) : [];
  const starters = groups.flatMap((g) => g.prompts).slice(0, 4);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (typed.length >= 3 && !asking) { onAsk(typed); setQ(""); }
  };

  // The three "working" steps advance on elapsed time only; the server reports no real progress.
  useEffect(() => {
    if (!asking) { setElapsed(0); return; }
    const began = Date.now();
    const id = window.setInterval(() => setElapsed(Date.now() - began), 250);
    return () => window.clearInterval(id);
  }, [asking]);

  // Keep the newest message in view inside the thread, without scrolling the whole page.
  useEffect(() => {
    const el = thread.current;
    if (!el) return;
    if (prefersReducedMotion()) el.scrollTop = el.scrollHeight;
    else el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [qas.length, asking]);

  const phase = phaseAt(elapsed);

  return (
    <div className="chat">
      <div className="thread chat-thread" ref={thread} role="log" aria-label="Conversation" aria-live="off" tabIndex={0}>
        {turns.length === 0 && !asking && (
          <div className="chat-empty">
            <h3>What do you want to understand?</h3>
            <p className="muted small">Ask anything about your day, in your own words. Each answer shows the memories it rests on.</p>
            <div className="examples starters">
              {starters.map((s) => <button type="button" key={s} disabled={asking} onClick={() => onAsk(s)}>{s}</button>)}
            </div>
          </div>
        )}

        {turns.map((qa) => (
          <article className={`qa ${qa.answer?.status ?? ""}`} key={qa.id} aria-label={`Question: ${qa.question}`}>
            <p className="q bubble me">{qa.question}</p>
            {qa.error && qa.error.notRecorded && (
              <NotRecorded question={qa.question} groups={groups} disabled={asking} onAsk={onAsk} />
            )}
            {qa.error && !qa.error.notRecorded && <div className="notice error" role="alert">{qa.error.text}</div>}
            {qa.answer && <Answered a={qa.answer} onCite={onCite} onWhy={onWhy} />}
          </article>
        ))}

        {asking && (
          <ol className="steps" role="status" aria-label="Looking through your memories">
            {PHASES.map((label, i) => (
              <li key={label} className={i < phase ? "done" : i === phase ? "now" : ""}>
                <span aria-hidden="true">{i < phase ? "✓" : i === phase ? "…" : "·"}</span> {label}
              </li>
            ))}
          </ol>
        )}

        {next.length > 0 && (
          <div className="examples follow" role="group" aria-label="Suggested next questions">
            {next.map((n) => <button type="button" key={n} onClick={() => onAsk(n)}>{n}</button>)}
          </div>
        )}
      </div>

      {near.length > 0 && (
        <div className="nearby" role="group" aria-label="Questions with recorded answers">
          <p className="small muted">Closest questions with a recorded answer</p>
          {near.map((n) => (
            <button type="button" key={n} disabled={asking} onClick={() => { setQ(""); onAsk(n); }}>{n}</button>
          ))}
        </div>
      )}

      <form className="ask-form chat-composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="question">Ask about your day</label>
        <input id="question" type="text" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off"
               placeholder={replay ? "Pick a question below, or type one…" : "Ask about your day, people or places…"} maxLength={500}
               aria-describedby={replay ? "ask-mode-note" : undefined} />
        <button type="submit" className="send" disabled={asking || typed.length < 3} aria-label={asking ? "Thinking" : "Ask"}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5m0 0-6 6m6-6 6 6" /></svg>
        </button>
      </form>
      <p className="small muted chat-note">Answers only use what is in your Atlas. Forgotten memories are never used.</p>

      {replay && (
        <p className="mode-note small" id="ask-mode-note">
          <span className="chip warn">Replay mode</span>
          <span>
            This demo answers a fixed set of questions from recordings, so it works offline. To ask anything, run
            with a live key (<a href="https://github.com/saiteja195/MemoryAtlas/blob/main/docs/LOCAL_SETUP.md#4-model-modes" target="_blank" rel="noopener">how</a>).
          </span>
        </p>
      )}

      <details className="more-prompts" open={examplesOpen} onToggle={(e) => setExamplesOpen(e.currentTarget.open)}>
        <summary>Example questions</summary>
        <div className="prompt-groups" role="group" aria-label="Example questions">
          {groups.map((g) => (
            <section key={g.title} className="prompt-group">
              <p className="prompt-title"><strong>{g.title}</strong> <span className="muted small">{g.hint}</span></p>
              <div className="examples">
                {g.prompts.map((ex) => (
                  <button type="button" key={ex} disabled={asking} onClick={() => onAsk(ex)}>{ex}</button>
                ))}
              </div>
            </section>
          ))}
        </div>
      </details>
    </div>
  );
}

function Answered({ a, onCite, onWhy }: { a: Answer; onCite: (id: string) => void; onWhy: (ids: string[]) => void }) {
  const s = STATUS[a.status];
  return (
    <div className="bubble bot">
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

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { LlmMode } from "../api/types";
import { followUps, oldestFirst, PHASES, phaseAt } from "../utils/chat";
import type { Turn } from "../utils/assistant";
import { prefersReducedMotion } from "../utils/theme";
import { Thread } from "./Thread";
import { AFTER_GROUPS, BEFORE_GROUPS, isKnown, suggest } from "../utils/suggest";
import type { Suggestions } from "../utils/assistant";

/** One question with its answer: the thread is a list of these, newest first. */
export type QA = Turn;

type Props = {
  qas: QA[];
  asking: boolean;
  forgotten: boolean;
  mode: LlmMode | undefined;
  /** Prompts built from the person's own memories (live mode). Replay mode keeps the recorded questions. */
  suggestions: Suggestions;
  selectedDay: string | null;
  loaded: boolean;
  onAsk: (q: string) => void;
  onCite: (claimId: string) => void;
  onWhy: (claimIds: string[]) => void;
};

export function AskPanel({ qas, asking, forgotten, mode, suggestions, selectedDay, loaded, onAsk, onCite, onWhy }: Props) {
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
  // Live: prompts built from this person's own memories. Replay: only the recorded questions can be answered.
  const live = !replay;
  const shown: typeof BEFORE_GROUPS = live
    ? suggestions.groups.map((g) => ({ title: g.title, hint: "", prompts: g.prompts }))
    : groups;
  const next = !asking && last?.answer ? followUps(qas.map((x) => x.question), shown) : [];
  const starters = shown.flatMap((g) => g.prompts).slice(0, 4);
  const nothingYet = live && suggestions.empty !== null;

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
        {turns.length === 0 && !asking && !loaded && <p className="muted small" role="status">Loading your conversation…</p>}
        {turns.length === 0 && !asking && loaded && (
          <div className="chat-empty">
            <h3>{nothingYet ? suggestions.empty : "What do you want to understand?"}</h3>
            <p className="muted small">
              {nothingYet
                ? "Add a photo, a voice note or a few words, and the questions you can ask will appear here."
                : "Ask anything about your day, in your own words. Each answer shows the memories it rests on."}
            </p>
            {!nothingYet && (
              <div className="examples starters">
                {starters.map((s) => <button type="button" key={s} disabled={asking} onClick={() => onAsk(s)}>{s}</button>)}
              </div>
            )}
          </div>
        )}

        <Thread turns={turns} asking={asking} phase={phase} groups={groups} selectedDay={selectedDay}
                onAsk={onAsk} onCite={onCite} onWhy={onWhy} />

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

      {shown.length > 0 && <details className="more-prompts" open={examplesOpen} onToggle={(e) => setExamplesOpen(e.currentTarget.open)}>
        <summary>Example questions</summary>
        <div className="prompt-groups" role="group" aria-label="Example questions">
          {shown.map((g) => (
            <section key={g.title} className="prompt-group">
              <p className="prompt-title"><strong>{g.title}</strong> {g.hint ? <span className="muted small">{g.hint}</span> : null}</p>
              <div className="examples">
                {g.prompts.map((ex) => (
                  <button type="button" key={ex} disabled={asking} onClick={() => onAsk(ex)}>{ex}</button>
                ))}
              </div>
            </section>
          ))}
        </div>
      </details>}
    </div>
  );
}

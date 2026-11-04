import { useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Goal, LlmMode, Me } from "../api/types";
import { addAvailability } from "../utils/addMemory";
import { CONSENT_STATEMENTS, followUps, GOALS, nextStep, type Step } from "../utils/onboarding";
import { AddMemory } from "./AddMemory";

type Props = {
  me: Me;
  mode: LlmMode | undefined;
  /** Reload who is signed in, after goals or consent were saved. */
  onChanged: () => Promise<void> | void;
  /** The person finished or skipped the last step. */
  onDone: () => void;
};

const STEPS: { id: Step; label: string }[] = [
  { id: "account", label: "Profile" },
  { id: "goals", label: "Goals" },
  { id: "consent", label: "Consent" },
  { id: "first-memory", label: "First memory" },
];

function errorText(e: unknown): string {
  return e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong. Please try again.";
}

/** Profile (done), goals, consent, first memory, then the dashboard. Each screen can be left and resumed. */
export function Onboarding({ me, mode, onChanged, onDone }: Props) {
  const step = nextStep({ signedIn: true, goalsSaved: me.profile.goals.length > 0, consented: me.profile.onboarded });
  const index = STEPS.findIndex((s) => s.id === step);

  return (
    <main className="onb">
      <div className="onb-card">
        <ol className="onb-progress" aria-label="Setup progress">
          {STEPS.map((s, i) => (
            <li key={s.id} className={i < index ? "done" : i === index ? "now" : ""} aria-current={i === index ? "step" : undefined}>
              <span className="onb-dot" aria-hidden="true">{i < index ? "✓" : i + 1}</span>
              <span className="onb-step-label">{s.label}<span className="sr-only">{i < index ? " (done)" : ""}</span></span>
            </li>
          ))}
          <li><span className="onb-dot" aria-hidden="true">5</span><span className="onb-step-label">Dashboard</span></li>
        </ol>

        {step === "goals" && <Goals name={me.profile.name} onSaved={onChanged} />}
        {step === "consent" && <Consent onAccepted={onChanged} />}
        {step === "first-memory" && <FirstMemory mode={mode} onDone={onDone} />}
      </div>
    </main>
  );
}

function Goals({ name, onSaved }: { name: string; onSaved: () => Promise<void> | void }) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});   // shown, not stored: goals are what personalise
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const questions = followUps(goals);

  const toggle = (g: Goal) => setGoals((cur) => (cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g]));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.setGoals(goals);
      await onSaved();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="onb-goals">
      <h1 id="onb-goals" className="onb-title">Welcome, {name}. How do you want to use MemoryAtlas?</h1>
      <p className="lede">Pick anything that fits. We use it to suggest what to ask first. You can change it later in Settings.</p>
      <fieldset className="onb-goals">
        <legend className="sr-only">What you want to use it for</legend>
        {GOALS.map((g) => (
          <label key={g.id} className={`onb-goal${goals.includes(g.id) ? " on" : ""}`}>
            <input type="checkbox" checked={goals.includes(g.id)} onChange={() => toggle(g.id)} />
            <span className="onb-goal-text"><strong>{g.label}</strong><span>{g.blurb}</span></span>
          </label>
        ))}
      </fieldset>

      {questions.map((q) => (
        <fieldset key={q.id} className="onb-q">
          <legend>{q.question}</legend>
          <div className="onb-opts">
            {q.options.map((o) => (
              <label key={o} className={`onb-opt${answers[q.id] === o ? " on" : ""}`}>
                <input type="radio" name={`fu-${q.id}`} checked={answers[q.id] === o} onChange={() => setAnswers((a) => ({ ...a, [q.id]: o }))} />
                {o}
              </label>
            ))}
          </div>
        </fieldset>
      ))}

      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="onb-actions">
        <button type="button" className="btn primary large" disabled={busy || goals.length === 0} onClick={() => void save()}>
          {busy ? "Saving…" : "Continue"}
        </button>
        {goals.length === 0 && <span className="small muted">Pick at least one.</span>}
      </div>
    </section>
  );
}

function Consent({ onAccepted }: { onAccepted: () => Promise<void> | void }) {
  const [ticked, setTicked] = useState<boolean[]>(CONSENT_STATEMENTS.map(() => false));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const all = ticked.every(Boolean);

  const agree = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.acceptConsent();
      await onAccepted();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="onb-consent">
      <h1 id="onb-consent" className="onb-title">What you are agreeing to</h1>
      <p className="lede">MemoryAtlas is built around consent. Please read and tick each line.</p>
      <fieldset className="onb-consent">
        <legend className="sr-only">Consent statements</legend>
        {CONSENT_STATEMENTS.map((s, i) => (
          <label key={s} className={`onb-check${ticked[i] ? " on" : ""}`}>
            <input type="checkbox" checked={ticked[i]} onChange={(e) => setTicked((t) => t.map((v, k) => (k === i ? e.target.checked : v)))} />
            <span>{s}</span>
          </label>
        ))}
      </fieldset>
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="onb-actions">
        <button type="button" className="btn primary large" disabled={!all || busy} onClick={() => void agree()}>
          {busy ? "Saving…" : "I agree"}
        </button>
        {!all && <span className="small muted">Tick all four to continue.</span>}
      </div>
    </section>
  );
}

function FirstMemory({ mode, onDone }: { mode: LlmMode | undefined; onDone: () => void }) {
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const added = useRef(false);
  const avail = addAvailability(mode);

  const sample = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.loadSample();
      onDone();
    } catch (e) {
      setError(errorText(e));
      setLoading(false);
    }
  };

  return (
    <section aria-labelledby="onb-first">
      <h1 id="onb-first" className="onb-title">Add your first memory</h1>
      <p className="lede">A photo, a voice note, a video or a few words. Muse reads it, asks only what it is unsure of, and keeps the text.</p>
      <div className="onb-choices">
        {avail.ok ? (
          <button type="button" className="onb-choice" disabled={loading} onClick={() => setAdding(true)}>
            <strong>Add a memory</strong>
            <span>Upload a file, take a photo, or write a note.</span>
          </button>
        ) : (
          <div className="onb-choice off">
            <strong>Add a memory</strong>
            <span>{avail.message}</span>
          </div>
        )}
        <button type="button" className="onb-choice" disabled={loading} onClick={() => void sample()}>
          <strong>{loading ? "Loading the sample day…" : "Try the sample day"}</strong>
          <span>{loading ? "Muse is reading a staged day. This can take a minute." : "Nothing to upload? Explore a ready-made day."}</span>
        </button>
      </div>
      {loading && <progress aria-label="Loading the sample day" />}
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="onb-actions">
        <button type="button" className="btn ghost" disabled={loading} onClick={onDone}>Skip for now</button>
      </div>

      <AddMemory open={adding} mode={mode}
                 onSaved={() => { added.current = true; }}
                 onClose={() => { setAdding(false); if (added.current) onDone(); }} />
    </section>
  );
}

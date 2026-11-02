import { useId, useState } from "react";

export type CorrectionBody = { text?: string; retract?: boolean; at?: string };

type Props = {
  claimText: string;
  replay: boolean;
  onSubmit: (body: CorrectionBody) => Promise<boolean>;
};

// The one correction recorded for replay mode. Its time is fixed because the time is part of what the
// recording was keyed on (backend/scripts/correct_demo.py).
export const RECORDED_CORRECTION: CorrectionBody = {
  text: "Actually, Alex said he would send the proposal by Monday, not Friday.",
  at: "2026-10-29T18:30:00",
};

/**
 * "That's wrong". The user can replace a remembered fact with what is right, or just set it aside.
 * Nothing is deleted: the old fact stays visible as history and answers stop using it.
 */
export function CorrectClaim({ claimText, replay, onSubmit }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const id = useId();
  const canUseExample = replay && /proposal/i.test(claimText);

  const send = async (body: CorrectionBody) => {
    setBusy(true);
    const ok = await onSubmit(body);
    setBusy(false);
    if (ok) { setOpen(false); setText(""); }
  };

  if (!open) {
    return <div className="row"><button type="button" className="btn small" onClick={() => setOpen(true)}>That's wrong…</button></div>;
  }
  return (
    <form className="correct" onSubmit={(e) => { e.preventDefault(); if (text.trim().length >= 3) void send({ text: text.trim() }); }}>
      <label htmlFor={id}>What is right?</label>
      <textarea id={id} value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={500}
                placeholder="For example: Alex said he would send it by Monday." disabled={busy} />
      {replay && (
        <p className="small muted">
          Replay mode: only the recorded correction works.{" "}
          {canUseExample && (
            <button type="button" className="btn small ghost" disabled={busy} onClick={() => setText(RECORDED_CORRECTION.text ?? "")}>
              Use the recorded example
            </button>
          )}
        </p>
      )}
      <div className="row">
        <button type="submit" className="btn primary small" disabled={busy || text.trim().length < 3}
                onClick={(e) => { if (replay && text.trim() === RECORDED_CORRECTION.text) { e.preventDefault(); void send(RECORDED_CORRECTION); } }}>
          Replace this fact
        </button>
        <button type="button" className="btn small" disabled={busy} onClick={() => void send({ retract: true })}>Just set it aside</button>
        <button type="button" className="btn small ghost" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
      </div>
      <p className="small muted">The earlier fact is kept as history, and anything that rested only on it is set aside too.</p>
    </form>
  );
}

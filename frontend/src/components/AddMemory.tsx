import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { api, ApiError } from "../api/client";
import type { CommitResult, Draft, DraftField, LlmMode, PreviewBody, Question } from "../api/types";
import {
  addAvailability, classifyFile, localIso, maxBytes, toCommitBody, unanswered, whenInputValue,
  type AnswerState, type FileKind,
} from "../utils/addMemory";
import { extractVideo, toBase64, toWav16k } from "../utils/media";
import { CaptureButtons, type Captured } from "./CaptureButtons";
import { Dialog } from "./Dialog";

type Source = { kind: FileKind; blob: Blob; name: string; modifiedAt: number };
type Step = "add" | "reading" | "review" | "saving" | "saved";

type Props = { open: boolean; mode: LlmMode | undefined; onClose: () => void; onSaved: () => void };

const KIND_WORD: Record<FileKind, string> = { frame: "Photo", audio: "Voice", video: "Video" };
const FIELD_LABEL: Record<DraftField["key"], string> = { when: "When", where: "Where", doing: "Doing", people: "People" };
const BADGE = { sure: { text: "Sure", cls: "ok" }, check: { text: "Check", cls: "warn" }, ask: { text: "Ask", cls: "warn" } } as const;
const SOURCE_WORD: Record<string, string> = {
  exif: "Photo metadata", file: "File date", image: "Read from the image", voice: "Heard in the audio",
  note: "Your note", user: "You",
};
const REASON: Record<string, string> = {
  no_consent: "someone in it did not agree",
  duplicate: "it is already in your Atlas",
  blocked: "it matches something you asked to forget",
  empty: "there was nothing to keep",
  bad_input: "it could not be read",
};

const fmtBytes = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function outcomeText(r: CommitResult): { text: string; saved: boolean } {
  const stored = r.results.filter((x) => x.status === "ingested");
  const claims = stored.reduce((n, x) => n + x.claims, 0);
  if (stored.length) {
    return { saved: true, text: `Saved. Muse found ${claims} fact${claims === 1 ? "" : "s"} in it and added ${claims === 1 ? "it" : "them"} to your Atlas.` };
  }
  const why = [...new Set(r.results.map((x) => REASON[x.reason ?? ""] ?? x.reason).filter(Boolean))].join("; ");
  return { saved: false, text: `Nothing was saved${why ? `: ${why}` : ""}.` };
}

export function AddMemory({ open, mode, onClose, onSaved }: Props) {
  const [source, setSource] = useState<Source | null>(null);
  const [note, setNote] = useState("");
  const [step, setStep] = useState<Step>("add");
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [answers, setAnswers] = useState<AnswerState>({ people: {} });
  const [placeChoice, setPlaceChoice] = useState<"yes" | "other" | null>(null);
  const [outcome, setOutcome] = useState<{ text: string; saved: boolean } | null>(null);
  const [grants, setGrants] = useState<CommitResult["grants"]>([]);
  const [hover, setHover] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const reset = () => {
    setSource(null); setNote(""); setStep("add"); setError(null); setDraft(null);
    setAnswers({ people: {} }); setPlaceChoice(null); setOutcome(null); setGrants([]); setHover(false);
  };
  useEffect(() => { if (!open) reset(); }, [open]);

  const take = (file: File) => {
    const c = classifyFile(file);
    if ("unsupported" in c) { setError(c.unsupported); return; }
    if (file.size > maxBytes(c.kind)) { setError(`That file is ${fmtBytes(file.size)}, over the ${fmtBytes(maxBytes(c.kind))} limit.`); return; }
    setError(null);
    setSource({ kind: c.kind, blob: file, name: file.name, modifiedAt: file.lastModified || 0 });
  };
  const onPick = (e: ChangeEvent<HTMLInputElement>) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) take(f); };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setHover(false); const f = e.dataTransfer.files[0]; if (f) take(f); };
  const onCaptured = (c: Captured) => {
    const kind: FileKind = c.kind === "photo" ? "frame" : c.kind === "voice" ? "audio" : "video";
    setError(null);
    setSource({ kind, blob: c.blob, name: c.name, modifiedAt: Date.now() });
  };

  const analyze = async () => {
    setError(null);
    setStep("reading");
    try {
      let body: PreviewBody;
      if (source) {
        // A file with no modified time sends none, so Muse asks when it happened instead of guessing.
        const when = source.modifiedAt ? localIso(source.modifiedAt) : undefined;
        if (source.kind === "frame") {
          body = { kind: "frame", data_b64: await toBase64(source.blob), file_modified_at: when };
        } else if (source.kind === "audio") {
          body = { kind: "audio", data_b64: await toBase64(await toWav16k(source.blob)), file_modified_at: when };
        } else {
          const v = await extractVideo(source.blob);
          body = {
            kind: "video", frames_b64: await Promise.all(v.frames.map(toBase64)), frame_offsets_ms: v.offsetsMs,
            audio_b64: v.audio ? await toBase64(v.audio) : undefined, file_modified_at: when,
          };
        }
      } else {
        body = { kind: "note", text: note.trim(), file_modified_at: localIso(Date.now()) };
      }
      setDraft(await api.previewCapture(body));
      setAnswers({ people: {} });
      setPlaceChoice(null);
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStep("add");
    }
  };

  const save = async () => {
    if (!draft) return;
    setError(null);
    setStep("saving");
    try {
      const result = await api.commitCapture(toCommitBody(draft, answers));
      const r = outcomeText(result);
      setGrants(result.grants);
      setOutcome(r);
      setStep("saved");
      if (r.saved) onSaved();
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : String(e));
      setStep("review");
    }
  };

  const open_ = draft ? unanswered(draft, answers) : [];
  const declined = Object.values(answers.people).some((p) => p.consented === false);
  const avail = addAvailability(mode);
  const canAnalyze = (source !== null || note.trim().length > 0) && step === "add";

  return (
    <Dialog open={open} onClose={onClose} title="Add a memory" className="add-dialog" initialFocus="[data-autofocus]">
      {open && !avail.ok && <div className="notice warn" role="status">{avail.message}</div>}

      {open && avail.ok && (step === "add" || step === "reading") && (
        <div className="add-step">
          <CaptureButtons disabled={step === "reading"} onCaptured={onCaptured} />

          <div
            className={`add-drop${hover ? " over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setHover(true); }}
            onDragLeave={() => setHover(false)} onDrop={onDrop}
          >
            <p><strong>Drop a file here</strong></p>
            <p className="small muted">Photo (JPEG or PNG), voice, or video</p>
            <button type="button" className="btn" data-autofocus disabled={step === "reading"} onClick={() => input.current?.click()}>Browse files</button>
            <input ref={input} type="file" className="sr-only" tabIndex={-1} accept="image/jpeg,image/png,audio/*,video/*" onChange={onPick} />
          </div>

          {source && (
            <div className="add-file">
              <span className="chip accent">{KIND_WORD[source.kind]}</span>
              <span className="add-name">{source.name}</span>
              <span className="small muted">{fmtBytes(source.blob.size)}</span>
              <button type="button" className="btn small ghost" disabled={step === "reading"} onClick={() => setSource(null)} aria-label={`Remove ${source.name}`}>Remove</button>
            </div>
          )}

          <label className="add-label" htmlFor="add-note">Or write a note</label>
          <textarea id="add-note" className="add-note" rows={3} maxLength={5000} value={note} disabled={source !== null || step === "reading"}
                    placeholder="Lunch with Alex near the office" onChange={(e) => setNote(e.target.value)} />
          {source && <p className="small muted">A note can only be added on its own. Remove the file to write one.</p>}

          {error && <div className="notice error" role="alert">{error}</div>}

          <div className="add-actions">
            {step === "reading" && <progress aria-label="Muse is reading it" />}
            <button type="button" className="btn primary" disabled={!canAnalyze} onClick={() => void analyze()}>
              {step === "reading" ? "Reading…" : "Analyze with Muse"}
            </button>
          </div>
          <p className="small muted">Muse reads it and turns it into text. The photo, audio or video itself is not kept, and nothing is saved until you press Save.</p>
        </div>
      )}

      {open && draft && (step === "review" || step === "saving") && (
        <div className="add-step">
          <h3>What Muse found</h3>
          <ul className="add-found">
            {draft.fields.map((f, i) => (
              <li key={`${f.key}${i}`}>
                <span className="k">{FIELD_LABEL[f.key]}</span>
                <span className="v">
                  {f.value ?? <span className="muted">Not found</span>}
                  {f.source && <span className="small muted"> · {SOURCE_WORD[f.source] ?? f.source}</span>}
                </span>
                <span className={`chip ${BADGE[f.confidence].cls}`}>{BADGE[f.confidence].text}</span>
              </li>
            ))}
          </ul>

          {draft.fields.some((f) => f.key === "when" && f.confidence === "check") && (
            <label className="add-when">
              <span className="add-label">Change the time if it is wrong</span>
              <input type="datetime-local" value={whenInputValue(draft, answers)}
                     onChange={(e) => setAnswers({ ...answers, when: e.target.value ? `${e.target.value}:00` : undefined })} />
            </label>
          )}

          {draft.questions.length > 0 && <h3>A few questions</h3>}
          {draft.questions.map((q) => {
            if (q.kind === "consent" && q.ref === answers.ownerSpeaker) return null;
            return (
              <QuestionCard key={q.id} q={q} draft={draft} answers={answers} placeChoice={placeChoice}
                            onPlaceChoice={setPlaceChoice} onChange={setAnswers} done={!open_.includes(q.id)} />
            );
          })}

          {declined && (
            <div className="notice warn" role="status">Saving will drop this memory: someone in it did not agree.</div>
          )}
          {error && <div className="notice error" role="alert">{error}</div>}

          <div className="add-actions">
            <button type="button" className="btn ghost" disabled={step === "saving"} onClick={reset}>Start over</button>
            <button type="button" className="btn primary" disabled={open_.length > 0 || step === "saving"} onClick={() => void save()}>
              {step === "saving" ? "Saving…" : declined ? "Save (will be dropped)" : "Save to Atlas"}
            </button>
          </div>
          {open_.length > 0 && <p className="small muted">{open_.length} question{open_.length === 1 ? "" : "s"} left.</p>}
        </div>
      )}

      {open && step === "saved" && outcome && (
        <div className="add-step" role="status">
          <div className={`notice ${outcome.saved ? "info" : "warn"}`}>{outcome.text}</div>
          {outcome.saved && grants.length > 0 && <WithdrawCodes grants={grants} />}
          <div className="add-actions">
            <button type="button" className="btn" onClick={reset}>Add another</button>
            <button type="button" className="btn primary" data-autofocus onClick={onClose}>Done</button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

/** Each consent record made by this upload, with the code that withdraws it. Shown once; the server keeps only a hash. */
function WithdrawCodes({ grants }: { grants: CommitResult["grants"] }) {
  const copy = (text: string) => { try { void navigator.clipboard?.writeText(text); } catch { /* the code is on screen */ } };
  return (
    <div className="add-codes">
      <h3>Withdrawing consent later</h3>
      <p className="small muted">
        Each person has a consent record. Keep its code: it is shown only now, and it is what lets that person
        withdraw their consent and have what rests on it forgotten.
      </p>
      <ul>
        {grants.map((g) => (
          <li key={g.grant_id}>
            <span><strong>{g.person === "me" ? "You" : g.person}</strong> <span className="small muted">{g.grant_id}</span></span>
            <code>{g.revocation_token}</code>
            <button type="button" className="btn small" onClick={() => copy(g.revocation_token)} aria-label={`Copy the code for ${g.person}`}>Copy</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function QuestionCard({ q, draft, answers, placeChoice, onPlaceChoice, onChange, done }: {
  q: Question; draft: Draft; answers: AnswerState; placeChoice: "yes" | "other" | null;
  onPlaceChoice: (c: "yes" | "other") => void; onChange: (a: AnswerState) => void; done: boolean;
}) {
  const set = (patch: Partial<AnswerState>) => onChange({ ...answers, ...patch });
  const person = q.ref ? answers.people[q.ref] ?? { name: "", consented: null } : null;
  const setPerson = (patch: Partial<NonNullable<typeof person>>) =>
    q.ref && onChange({ ...answers, people: { ...answers.people, [q.ref]: { ...person!, ...patch } } });
  const pill = (label: string, active: boolean, onClick: () => void) => (
    <button type="button" className="btn" aria-pressed={active} onClick={onClick} key={label}>{label}</button>
  );

  return (
    <fieldset className={`add-q${done ? " done" : ""}`}>
      <legend>{q.prompt}</legend>

      {q.kind === "datetime" && (
        <input type="datetime-local" aria-label={q.prompt} value={(answers.when ?? "").slice(0, 16)}
               onChange={(e) => set({ when: e.target.value ? `${e.target.value}:00` : undefined })} />
      )}

      {q.id === "where" && (
        <input type="text" aria-label={q.prompt} maxLength={200} value={answers.where ?? ""}
               placeholder="e.g. Mikado Ramen" onChange={(e) => set({ where: e.target.value })} />
      )}

      {q.id === "where_confirm" && (
        <>
          <div className="opts">
            {pill("Yes", placeChoice === "yes", () => { onPlaceChoice("yes"); set({ where: null }); })}
            {pill("Different place", placeChoice === "other", () => { onPlaceChoice("other"); set({ where: "" }); })}
          </div>
          {placeChoice === "other" && (
            <input type="text" aria-label="The place" maxLength={200} value={answers.where ?? ""}
                   placeholder="What is it called?" onChange={(e) => set({ where: e.target.value })} />
          )}
        </>
      )}

      {q.id === "owner_speaker" && (
        <div className="opts">{q.options.map((o) => pill(`Speaker ${o}`, answers.ownerSpeaker === o, () => set({ ownerSpeaker: o })))}</div>
      )}

      {q.kind === "consent" && person && (
        <>
          {draft.speakers.includes(q.ref ?? "") && (
            <input type="text" aria-label={`Name for ${q.ref}`} maxLength={80} value={person.name} placeholder="Name"
                   onChange={(e) => setPerson({ name: e.target.value })} />
          )}
          <div className="opts">
            {pill("Yes, they agreed", person.consented === true, () => setPerson({ consented: true }))}
            {pill("No", person.consented === false, () => setPerson({ consented: false }))}
          </div>
        </>
      )}
    </fieldset>
  );
}

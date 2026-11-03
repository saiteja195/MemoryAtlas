import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Goal, Me } from "../api/types";
import { CONSENT_STATEMENTS, GOALS } from "../utils/onboarding";
import { authMessage } from "./AuthGate";
import { Dialog } from "./Dialog";

type Props = {
  open: boolean;
  me: Me;
  onClose: () => void;
  /** Goals changed: reload who is signed in. */
  onChanged: () => Promise<void> | void;
  /** The demo data was reset (demo profiles only): reload everything on screen. */
  onResetDemo: () => Promise<void> | void;
  /** The profile was deleted or the person signed out. */
  onSignedOut: () => void;
};

/** Goals, what was agreed, and the two irreversible things: reset a demo profile, delete your profile. */
export function Settings({ open, me, onClose, onChanged, onResetDemo, onSignedOut }: Props) {
  const p = me.profile;
  const [goals, setGoals] = useState<Goal[]>(p.goals);
  const [saved, setSaved] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setGoals(p.goals); setSaved(false); setConfirmReset(false); setConfirmDelete(false);
      setPasscode(""); setBusy(null); setError(null);
    }
  }, [open, p.goals]);

  const changed = goals.length !== p.goals.length || goals.some((g) => !p.goals.includes(g));
  const toggle = (g: Goal) => { setSaved(false); setGoals((c) => (c.includes(g) ? c.filter((x) => x !== g) : [...c, g])); };

  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    setError(null);
    try { await fn(); } catch (e) { setError(e instanceof ApiError ? authMessage(e) : e instanceof Error ? e.message : authMessage(e)); } finally { setBusy(null); }
  };

  const saveGoals = () => run("goals", async () => { await api.setGoals(goals); await onChanged(); setSaved(true); });
  const reset = () => run("reset", async () => { await onResetDemo(); setConfirmReset(false); onClose(); });
  const remove = () => run("delete", async () => {
    try { await api.deleteMe(passcode); } catch (e) {
      if (e instanceof ApiError && e.status === 401) throw new Error("That passcode is not right.");
      throw e;
    }
    onSignedOut();
  });

  return (
    <Dialog open={open} onClose={onClose} title="Settings" className="settings-dialog">
      <div className="set-body">
        <section aria-labelledby="set-profile">
          <h3 id="set-profile">Profile</h3>
          <p>
            <strong>{p.name}</strong>{" "}
            {p.demo_kind && <span className="chip accent">Demo profile</span>}
          </p>
          {p.demo_kind && <p className="small muted">Anyone can sign in to a demo profile, so it holds only demo content.</p>}
        </section>

        <section aria-labelledby="set-goals">
          <h3 id="set-goals">What you use it for</h3>
          <p className="small muted">This shapes the questions and cards we suggest.</p>
          <fieldset className="onb-goals">
            <legend className="sr-only">Goals</legend>
            {GOALS.map((g) => (
              <label key={g.id} className={`onb-goal${goals.includes(g.id) ? " on" : ""}`}>
                <input type="checkbox" checked={goals.includes(g.id)} onChange={() => toggle(g.id)} />
                <span className="onb-goal-text"><strong>{g.label}</strong><span>{g.blurb}</span></span>
              </label>
            ))}
          </fieldset>
          <div className="onb-actions">
            <button type="button" className="btn primary" disabled={!changed || goals.length === 0 || busy !== null} onClick={() => void saveGoals()}>
              {busy === "goals" ? "Saving…" : "Save goals"}
            </button>
            {saved && <span className="small" role="status">Saved.</span>}
          </div>
        </section>

        <section aria-labelledby="set-consent">
          <h3 id="set-consent">What you agreed to {p.onboarded && <span className="chip ok">Agreed</span>}</h3>
          <ul className="set-consent">
            {CONSENT_STATEMENTS.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </section>

        {p.demo_kind && (
          <section aria-labelledby="set-reset">
            <h3 id="set-reset">Reset demo data</h3>
            <p className="small muted">Puts this demo profile back to how it started. Anything you added is removed.</p>
            {!confirmReset ? (
              <button type="button" className="btn" onClick={() => setConfirmReset(true)}>Reset demo data…</button>
            ) : (
              <div className="onb-actions">
                <button type="button" className="btn danger" disabled={busy !== null} onClick={() => void reset()}>
                  {busy === "reset" ? "Resetting…" : "Yes, reset it"}
                </button>
                <button type="button" className="btn ghost" disabled={busy !== null} onClick={() => setConfirmReset(false)}>Cancel</button>
              </div>
            )}
          </section>
        )}

        {!p.demo_kind && (
          <section aria-labelledby="set-delete">
            <h3 id="set-delete">Delete my profile</h3>
            <p className="small muted">
              Removes your profile and every memory in it, for good. It cannot be undone, and there is no way to get it back.
            </p>
            {!confirmDelete ? (
              <button type="button" className="btn danger" onClick={() => setConfirmDelete(true)}>Delete my profile…</button>
            ) : (
              <form className="set-delete" onSubmit={(e) => { e.preventDefault(); void remove(); }}>
                <label className="auth-field">
                  <span>Type your passcode to confirm</span>
                  <input type="password" value={passcode} onChange={(e) => setPasscode(e.target.value)} autoComplete="current-password" />
                </label>
                <div className="onb-actions">
                  <button type="submit" className="btn danger" disabled={!passcode || busy !== null}>
                    {busy === "delete" ? "Deleting…" : "Delete everything"}
                  </button>
                  <button type="button" className="btn ghost" disabled={busy !== null} onClick={() => { setConfirmDelete(false); setPasscode(""); setError(null); }}>Cancel</button>
                </div>
              </form>
            )}
          </section>
        )}

        {error && <div className="notice error" role="alert">{error}</div>}

        <section aria-labelledby="set-out">
          <h3 id="set-out" className="sr-only">Sign out</h3>
          <button type="button" className="btn" onClick={onSignedOut}>Sign out</button>
        </section>
      </div>
    </Dialog>
  );
}

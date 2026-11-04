import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import { validateName, validatePasscode } from "../utils/onboarding";

type Props = { onSignedIn: () => void; unreachable?: string | null };
type Tab = "signin" | "signup";

/** What went wrong, in words a person can act on. Locked and rate-limited replies say how long to wait. */
export function authMessage(e: unknown): string {
  if (!(e instanceof ApiError)) return "MemoryAtlas could not be reached. Check your connection and try again.";
  if (e.isLocked) {
    const mins = e.retryAfter ? Math.max(1, Math.ceil(e.retryAfter / 60)) : null;
    return `Too many attempts. ${mins ? `Try again in ${mins} minute${mins === 1 ? "" : "s" }.` : "Try again in a little while."}`;
  }
  if (e.status === 401) return "That name and passcode do not match. Check them and try again.";
  if (e.status === 409) return "That name is taken. Pick another, or sign in.";
  if (e.status === 503) return "This app has reached its profile limit.";
  return e.message;
}

/** The first screen: sign in to your profile, or create one. There is no email and no passcode reset. */
export function AuthGate({ onSignedIn, unreachable }: Props) {
  const [tab, setTab] = useState<Tab>("signin");
  const [name, setName] = useState("");
  const [passcode, setPasscode] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const problem = tab === "signup" ? validateName(name) ?? validatePasscode(passcode) : null;
    if (problem) return setError(problem);
    if (!name.trim() || !passcode) return setError("Enter your name and passcode.");
    setBusy(true);
    setError(null);
    try {
      if (tab === "signup") await api.signup({ name, passcode });
      else await api.signin({ name, passcode });
      onSignedIn();
    } catch (e) {
      setError(authMessage(e));
      setBusy(false);
    }
  };

  const pick = (t: Tab) => { setTab(t); setError(null); };
  const signup = tab === "signup";

  return (
    <main className="auth">
      <div className="auth-card">
        <aside className="auth-hero">
          <p className="eyebrow">MemoryAtlas</p>
          <h1 className="auth-title">Remember your day. Ask it anything. Forget on command.</h1>
          <ul className="auth-points">
            <li><span aria-hidden="true">🔒</span><div><strong>Private by design</strong>You see only your own memories.</div></li>
            <li><span aria-hidden="true">✨</span><div><strong>Muse does the filing</strong>Add a photo, voice note or text. It asks only what it is unsure of.</div></li>
            <li><span aria-hidden="true">🗑️</span><div><strong>Forget on command</strong>Delete any memory, or your whole profile, at any time.</div></li>
          </ul>
        </aside>

        <section className="auth-panel">
          <div className="auth-tabs" role="tablist" aria-label="Sign in or create a profile">
            <button type="button" role="tab" id="tab-signin" aria-selected={!signup} aria-controls="auth-panel" onClick={() => pick("signin")}>Sign in</button>
            <button type="button" role="tab" id="tab-signup" aria-selected={signup} aria-controls="auth-panel" onClick={() => pick("signup")}>Create profile</button>
          </div>

          <div className="auth-head">
            <h2>{signup ? "Create your profile" : "Welcome back"}</h2>
            <p className="muted">{signup ? "Pick a name and a passcode. It takes under a minute." : "Sign in with your name and passcode."}</p>
          </div>

          <form id="auth-panel" role="tabpanel" aria-labelledby={signup ? "tab-signup" : "tab-signin"} className="auth-form" onSubmit={submit} noValidate>
            <div className="auth-field">
              <label htmlFor="auth-name">Name</label>
              <input id="auth-name" type="text" name="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="username"
                     autoCapitalize="words" spellCheck={false} maxLength={80} placeholder="e.g. Alex" required />
            </div>
            <div className="auth-field">
              <label htmlFor="auth-passcode">Passcode</label>
              <div className="auth-pass">
                <input id="auth-passcode" type={show ? "text" : "password"} name="passcode" value={passcode} onChange={(e) => setPasscode(e.target.value)}
                       autoComplete={signup ? "new-password" : "current-password"} maxLength={300} required
                       placeholder={signup ? "At least 6 characters" : "Your passcode"}
                       aria-describedby={signup ? "auth-hint" : undefined} />
                <button type="button" className="auth-eye" onClick={() => setShow(!show)} aria-pressed={show}
                        aria-label={show ? "Hide passcode" : "Show passcode"}>{show ? "Hide" : "Show"}</button>
              </div>
            </div>
            {signup && (
              <p id="auth-hint" className="small muted">
                There is no passcode reset: if you forget it, you will need a new profile.
              </p>
            )}
            {(error || unreachable) && <div className="notice error" role="alert">{error ?? unreachable}</div>}
            <button type="submit" className="btn primary large" disabled={busy}>
              {busy ? "One moment…" : signup ? "Create profile" : "Sign in"}
            </button>
          </form>

          <p className="small muted auth-switch">
            {signup ? "Already have a profile? " : "New here? "}
            <button type="button" className="auth-link" onClick={() => pick(signup ? "signin" : "signup")}>
              {signup ? "Sign in instead" : "Create a free profile"}
            </button>
          </p>
          <p className="small muted auth-foot">
            Reviewing this project? The demo profiles and their passcodes are listed in the README.
          </p>
        </section>
      </div>
    </main>
  );
}

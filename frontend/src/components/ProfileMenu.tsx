import { useEffect, useRef } from "react";

type Props = { name: string; onSettings: () => void; onSignOut: () => void };

/** The signed-in person's name, with Settings and Sign out. A native <details> keeps it keyboard-friendly. */
export function ProfileMenu({ name, onSettings, onSignOut }: Props) {
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const away = (e: Event) => {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) ref.current.open = false;
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && ref.current?.open) { ref.current.open = false; ref.current.querySelector("summary")?.focus(); }
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, []);

  const pick = (fn: () => void) => () => { if (ref.current) ref.current.open = false; fn(); };

  return (
    <details className="profile-menu" ref={ref}>
      <summary className="btn" aria-label={`Profile menu for ${name}`}>
        <span className="avatar" aria-hidden="true">{name.trim().charAt(0).toUpperCase()}</span>
        <span className="profile-name">{name}</span>
      </summary>
      <div className="profile-pop" role="group" aria-label="Profile">
        <button type="button" className="btn ghost" onClick={pick(onSettings)}>Settings</button>
        <button type="button" className="btn ghost" onClick={pick(onSignOut)}>Sign out</button>
      </div>
    </details>
  );
}

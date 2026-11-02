import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

// One polite live region for the whole page, as the accessibility guidance recommends: many
// regions become noise. Use sparingly: "answer ready", "graph updated", "consent withdrawn".
const Ctx = createContext<(msg: string) => void>(() => {});
export const useAnnounce = () => useContext(Ctx);

export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState("");
  const timer = useRef<number>();
  const announce = useCallback((m: string) => {
    window.clearTimeout(timer.current);
    setMsg("");
    // Clear first so repeating the same sentence is announced again; wait a beat so it does not
    // collide with focus changes.
    timer.current = window.setTimeout(() => setMsg(m), 120);
  }, []);
  return (
    <Ctx.Provider value={announce}>
      {children}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{msg}</div>
    </Ctx.Provider>
  );
}

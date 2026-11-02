import { useCallback, useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";
const KEY = "memoryatlas-theme";

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch { return "system"; }
}

function apply(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
}

/**
 * Light, dark or follow the system. The choice is stored in this browser only. `tick` changes
 * whenever the look changes, so the graph canvas knows to re-read its colours.
 */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(read);
  const [tick, setTick] = useState(0);

  useEffect(() => { apply(pref); setTick((t) => t + 1); }, [pref]);

  const choose = useCallback((p: ThemePref) => {
    setPref(p);
    try { if (p === "system") localStorage.removeItem(KEY); else localStorage.setItem(KEY, p); } catch { /* private mode */ }
  }, []);

  return { pref, choose, tick };
}

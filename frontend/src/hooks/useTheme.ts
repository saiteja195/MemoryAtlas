import { useCallback, useEffect, useState } from "react";

import { parseTheme, type ThemePref } from "../utils/themePref";

export type { ThemePref };
const KEY = "memoryatlas-theme";

function read(): ThemePref {
  try { return parseTheme(localStorage.getItem(KEY)); } catch { return "light"; }
}

function apply(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
}

/**
 * Light (the default), dark or follow the system. The choice is stored in this browser only. `tick` changes
 * whenever the look changes, so the graph canvas knows to re-read its colours.
 */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(read);
  const [tick, setTick] = useState(0);

  useEffect(() => { apply(pref); setTick((t) => t + 1); }, [pref]);

  const choose = useCallback((p: ThemePref) => {
    setPref(p);
    try { localStorage.setItem(KEY, p); } catch { /* private mode */ }
  }, []);

  return { pref, choose, tick };
}

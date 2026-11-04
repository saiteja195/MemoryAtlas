import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Answer } from "../api/types";
import { turnsFromHistory, type Turn } from "../utils/assistant";

type Options = {
  /** Called with every answer that arrives, so the page can show what it cited. */
  onAnswer?: (a: Answer) => void;
};

/**
 * The one conversation shared by every page. It is loaded from the server when it first mounts (so a reload
 * shows the same thread), and each question is sent with the day on screen. Turns are kept newest first.
 */
export function useAssistant(day: string | null, options: Options = {}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [asking, setAsking] = useState(false);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const next = useRef(0);
  const opts = useRef(options);
  opts.current = options;

  useEffect(() => {
    let live = true;
    api.chat()
      .then((messages) => {
        if (!live) return;
        const history = turnsFromHistory(messages);
        next.current = Math.max(next.current, history.length);
        setTurns((now) => [...now, ...history]);
      })
      .catch(() => undefined)               // no history is not an error: the thread just starts empty
      .finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, []);

  const ask = useCallback(async (question: string) => {
    const id = ++next.current;
    setAsking(true);
    try {
      const answer = await api.ask(question, day);
      setTurns((t) => [{ id, question, answer, asOf: day }, ...t]);
      opts.current.onAnswer?.(answer);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      setTurns((t) => [{ id, question, asOf: day,
        error: { text: e instanceof Error ? e.message : String(e), notRecorded: !!err?.isNotRecorded } }, ...t]);
    } finally {
      setAsking(false);
    }
  }, [day]);

  const clear = useCallback(() => setTurns([]), []);

  return { turns, loaded, asking, ask, clear, open, setOpen, expanded, setExpanded };
}

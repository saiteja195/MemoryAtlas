import { useEffect, useRef } from "react";
import type { LlmMode } from "../api/types";
import type { useAssistant } from "../hooks/useAssistant";
import { isLauncherShortcut, type Suggestions } from "../utils/assistant";
import { AskPanel } from "./AskPanel";

type Props = {
  assistant: ReturnType<typeof useAssistant>;
  suggestions: Suggestions;
  selectedDay: string | null;
  mode: LlmMode | undefined;
  forgotten: boolean;
  onCite: (claimId: string) => void;
  onWhy: (claimIds: string[]) => void;
};

/**
 * The one assistant, on every page: a launcher in the corner that opens a docked panel, which can expand to a full
 * sheet. Cmd/Ctrl+K toggles it and Escape closes it; focus moves to the question box on open and back to the
 * launcher on close. The conversation lives in `assistant`, above the pages, so it is the same everywhere.
 */
export function Assistant({ assistant, suggestions, selectedDay, mode, forgotten, onCite, onWhy }: Props) {
  const { open, setOpen, expanded, setExpanded } = assistant;
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isLauncherShortcut(e)) { e.preventDefault(); setOpen(!open); }
      // Escape belongs to a dialog that is open on top (a receipt, the evidence drawer): leave it alone.
      else if (e.key === "Escape" && open && !document.querySelector("dialog[open]")) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  useEffect(() => {
    if (open) panel.current?.querySelector<HTMLInputElement>("#question")?.focus();
    else if (wasOpen.current) launcher.current?.focus();
    wasOpen.current = open;
  }, [open]);

  return (
    <>
      {!open && (
        <button type="button" ref={launcher} className="assistant-launch" onClick={() => setOpen(true)}
                aria-haspopup="dialog" aria-keyshortcuts="Control+K Meta+K">
          <span aria-hidden="true">✦</span> Ask your memory <kbd aria-hidden="true">⌘K</kbd>
        </button>
      )}
      {open && (
        <section ref={panel} className={`assistant ${expanded ? "expanded" : "docked"}`} role="dialog"
                 aria-label="Ask your memory" aria-modal={expanded ? true : undefined}>
          <header className="assistant-head">
            <h2><span aria-hidden="true">✦</span> Ask your memory</h2>
            <div className="assistant-tools">
              <button type="button" className="icon-btn" onClick={() => setExpanded(!expanded)}
                      aria-pressed={expanded} aria-label={expanded ? "Shrink the assistant" : "Expand the assistant"}
                      title={expanded ? "Shrink" : "Expand"}>{expanded ? "⤡" : "⤢"}</button>
              <button type="button" className="icon-btn" onClick={() => setOpen(false)} aria-label="Close the assistant" title="Close">✕</button>
            </div>
          </header>
          <div className="assistant-body">
            <AskPanel qas={assistant.turns} asking={assistant.asking} forgotten={forgotten} mode={mode}
                      suggestions={suggestions} selectedDay={selectedDay} loaded={assistant.loaded}
                      onAsk={(q) => void assistant.ask(q)} onCite={onCite} onWhy={onWhy} />
          </div>
        </section>
      )}
    </>
  );
}

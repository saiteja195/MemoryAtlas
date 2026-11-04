// Small pure helpers for the to-do list.
import type { Todo } from "../api/types";
import { cleanText } from "./cardText";

/** "You said so · 12:40 conversation" or "Alex asked · 12:35 conversation": who, and when and where it was said. */
export function todoMeta(t: Todo): string {
  const lead = t.kind === "promise" ? "You said so" : `${cleanText(t.who) || "Someone"} asked`;
  const where = [cleanText(t.when), cleanText(t.source_label)].filter(Boolean).join(" ");
  return where ? `${lead} · ${where}` : lead;
}

/** Open items, latest first (an item without a time goes last); done items as the server gave them; dismissed ones are gone. */
export function splitByState(items: readonly Todo[]): { open: Todo[]; done: Todo[] } {
  const open = items.filter((t) => t.state === "open")
    .map((t, i) => ({ t, i }))
    .sort((a, b) => (b.t.when ?? "").localeCompare(a.t.when ?? "") || a.i - b.i)
    .map(({ t }) => t);
  return { open, done: items.filter((t) => t.state === "done") };
}

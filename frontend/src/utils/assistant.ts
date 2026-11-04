// What the assistant offers to ask, how a saved conversation becomes turns, and the launcher shortcut.
// Pure functions, tested without a browser.
import type { Answer, ChatMessage, Goal, Graph } from "../api/types";
import { cleanText } from "./cardText";
import { OWNER_ID, type Selection } from "./graph";

export type PromptGroup = {
  title: "About this" | "Facts" | "Summary" | "To-dos" | "About my memory";
  prompts: string[];
};

export type Suggestions = { empty: string | null; groups: PromptGroup[] };

export type SuggestionInput = {
  graph: Graph;
  goals: readonly Goal[];
  todosOpen: number;
  selection: Selection;
  hasMemories: boolean;
  /** The longest stretch with no memories on the day shown, when there is one. */
  gap?: { start: string; end: string } | null;
};

const MAX_PROMPT = 90;
const ORDER: PromptGroup["title"][] = ["Facts", "Summary", "To-dos", "About my memory"];
/** The group a goal cares about most. */
const GOAL_FIRST: Record<Goal, PromptGroup["title"]> = {
  remember_day: "Summary", work_meetings: "To-dos", trips: "Facts", family_friends: "Facts", just_trying: "Summary",
};

type Named = { id: string; type: string; name: string };

/** People, places and things that have a real name: a blank name never becomes a prompt. */
function named(graph: Graph): Named[] {
  return graph.nodes
    .filter((n) => n.type !== "episode" && n.id !== OWNER_ID)
    .map((n) => ({ id: n.id, type: n.type, name: cleanText(n.name) }))
    .filter((n) => n.name !== "");
}

function aboutThis(n: Named): string[] {
  if (n.type === "person") return [`When did I meet ${n.name}?`, `What did ${n.name} say?`, `What do I know about ${n.name}?`];
  if (n.type === "place") return [`What happened at ${n.name}?`, `When was I at ${n.name}?`, `What do I know about ${n.name}?`];
  return [`Where did I leave my ${n.name}?`, `When did I last see my ${n.name}?`, `What do I know about my ${n.name}?`];
}

export function buildSuggestions(input: SuggestionInput): Suggestions {
  if (!input.hasMemories) return { empty: "Add a memory to start", groups: [] };
  const all = named(input.graph);
  const person = all.find((n) => n.type === "person");
  const place = all.find((n) => n.type === "place");
  const thing = all.find((n) => n.type !== "person" && n.type !== "place");

  const by: Record<PromptGroup["title"], string[]> = {
    "About this": [],
    Facts: [
      ...(thing ? [`Where did I leave my ${thing.name}?`] : []),
      ...(person && place ? [`Which restaurant did ${person.name} recommend?`] : []),
      ...(person ? ["Who did I meet today?", `What time was my meeting with ${person.name}?`] : []),
    ],
    Summary: [
      "Summarise my day.", "What happened this morning?", "What was the most important moment?",
      ...(place ? ["Where did I spend the most time?"] : []),
    ],
    "To-dos": [
      "What did I say I would do today?", "Did I promise anyone anything?", "Did anyone ask me to do something?",
      "What did I forget to follow up on?",
    ],
    "About my memory": [
      "What did the models read today?", "How much of my day is covered?",
      ...(input.gap ? [`What happened between ${input.gap.start} and ${input.gap.end}?`] : []),
      "What are you unsure about?",
    ],
  };

  const first = input.goals.length ? GOAL_FIRST[input.goals[0]] : null;
  const order: PromptGroup["title"][] = first ? [first, ...ORDER.filter((t) => t !== first)] : ORDER;
  const picked = input.selection?.kind === "entity" ? all.find((n) => n.id === input.selection?.id) : undefined;
  if (picked) by["About this"] = aboutThis(picked);

  const seen = new Set<string>();
  const groups: PromptGroup[] = [];
  for (const title of picked ? (["About this", ...order] as PromptGroup["title"][]) : order) {
    const prompts = by[title].filter((p) => p.length <= MAX_PROMPT && !seen.has(p));
    prompts.forEach((p) => seen.add(p));
    if (prompts.length) groups.push({ title, prompts });
  }
  return { empty: null, groups };
}

/** One question with its answer (or the error that stopped it): what the thread shows. Ids only order them. */
export type Turn = {
  id: number;
  question: string;
  answer?: Answer;
  error?: { text: string; notRecorded: boolean };
  /** The day the question was asked about. */
  asOf?: string | null;
};

/** The saved conversation as turns, newest first (the order the thread is kept in). */
export function turnsFromHistory(messages: readonly ChatMessage[]): Turn[] {
  const turns: Turn[] = [];
  let id = 0;
  for (const m of messages) {
    if (m.role === "user") {
      turns.push({ id: ++id, question: m.text, asOf: m.as_of });
    } else if (turns.length && turns[turns.length - 1].answer === undefined) {
      turns[turns.length - 1].answer = {
        status: m.status ?? "abstained", answer: m.text, cited_claim_ids: m.cited_claim_ids, uncertainty_note: "",
        citations: m.citations, trace: [], steps: 0, checks: [], cached: false, cited_tools: m.cited_tools,
      };
    }
  }
  return turns.reverse();
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "28 Oct" when a message is about another day than the one on screen; nothing when they match or it is unknown. */
export function dayChip(messageDay: string | null | undefined, selectedDay: string | null | undefined): string | null {
  if (!messageDay || messageDay === selectedDay) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(messageDay);
  if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) return null;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
}

/** Cmd+K or Ctrl+K, with no other modifier. */
export function isLauncherShortcut(e: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }): boolean {
  return e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey;
}

/**
 * The conversation after it was read from the server again (forgetting redacts saved answers): the saved turns are the
 * truth, and a question that failed and was never saved stays in front, newest first.
 */
export function mergeHistory(local: readonly Turn[], saved: readonly Turn[]): Turn[] {
  // Saved turns are numbered 1, 2, ...; a kept unsaved one takes the negative of its id, so no two ever share a key.
  return [...local.filter((t) => t.error !== undefined).map((t) => ({ ...t, id: -Math.abs(t.id) })), ...saved];
}

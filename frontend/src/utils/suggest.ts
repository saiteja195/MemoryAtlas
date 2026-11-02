// The questions that have recorded answers (fixtures/demo_day/acts.yaml), and a small matcher
// that finds the closest one to what someone typed. Keep this list in step with that file.

export type Prompt = { text: string };
export type PromptGroup = { title: string; hint: string; prompts: string[] };

/** Before a forgetting. All of these were recorded with the day played and the car photo not yet uploaded. */
export const BEFORE_GROUPS: PromptGroup[] = [
  { title: "Connect the dots", hint: "No single source holds the answer", prompts: [
    "Which restaurant did Alex recommend when we met near the office?",
    "What was the name of the taco place Alex told me about?",
    "Where should I go for al pastor, according to Alex?",
  ] },
  { title: "Where is my wallet?", hint: "Answers change when newer evidence arrives", prompts: [
    "Where is my wallet?",
    "Did I leave my wallet at the café?",
    "When and where did I last see my wallet?",
  ] },
  { title: "Things it cannot know", hint: "It should say there is no record", prompts: [
    "What is Alex's phone number?",
    "Which gym did I go to?",
    "Who did I have lunch with on Friday?",
  ] },
];

/** After someone withdrew consent. */
export const AFTER_GROUPS: PromptGroup[] = [
  { title: "What was forgotten", hint: "Only the withdrawn conversation supported these", prompts: [
    "What did Alex promise me?",
    "Which restaurant did Alex recommend when we met near the office?",
    "What did Alex say about food?",
    "What was the deadline for the proposal Alex mentioned?",
  ] },
  { title: "What is still known", hint: "Other consented sources still support these", prompts: [
    "Did I have a meeting with Alex?",
    "What colour is the awning at Luna Taqueria?",
    "What did the billboard advertise?",
    "Where is my wallet?",
  ] },
];

const STOP = new Set(["the", "a", "an", "is", "was", "did", "do", "i", "me", "my", "to", "of", "at", "in", "on", "and", "or", "for", "what", "which", "where", "when", "who", "how", "about", "with", "that", "this", "it", "us", "we", "you", "your", "are", "were", "get"]);

const words = (s: string): string[] =>
  s.toLowerCase().replace(/[^a-z0-9'\s]/g, " ").split(/\s+/).map((w) => w.replace(/'s$/, "").replace(/(?<=[a-z]{3})s$/, "")).filter((w) => w.length > 2 && !STOP.has(w));

const MIN_SCORE = 0.35;

/** Up to `n` known questions that share the most meaningful words with `query`, best first. */
export function suggest(query: string, groups: PromptGroup[], n = 3): string[] {
  const q = new Set(words(query));
  if (q.size === 0) return [];
  const scored = [...new Set(groups.flatMap((g) => g.prompts))].map((p) => {
    const w = new Set(words(p));
    const shared = [...q].filter((x) => w.has(x)).length;
    return { p, score: shared / Math.sqrt(q.size * Math.max(w.size, 1)) };
  });
  // A single shared name ("Alex") is not enough to call two questions alike.
  return scored.filter((s) => s.score >= MIN_SCORE).sort((a, b) => b.score - a.score).slice(0, n).map((s) => s.p);
}

/** Does the text match a known question exactly (ignoring case and spacing)? */
export const isKnown = (text: string, groups: PromptGroup[]): boolean =>
  groups.some((g) => g.prompts.some((p) => p.toLowerCase() === text.trim().toLowerCase()));

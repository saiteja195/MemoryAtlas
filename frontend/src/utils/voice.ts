// The stored sentences name the person who owns the memory "Me" ("Me was at Office", "Alex asked Me to ..."). On screen
// they are spoken to: "You were at Office", "Alex asked you to ...". Display only: nothing stored is changed, and the
// model prompts that make the sentences stay as they are.
const AGREE: Record<string, string> = { was: "were", is: "are", has: "have", does: "do" };

/** "Me was at the cafe." becomes "You were at the cafe."; "Alex asked Me to go." becomes "Alex asked you to go." */
export function youify(text: string): string {
  if (!text || !/\bMe\b/.test(text)) return text;
  return text
    .replace(/(^|[.!?]\s+)Me's\b/g, "$1Your")
    .replace(/\bMe's\b/g, "your")
    .replace(/(^|[.!?]\s+)Me\b/g, "$1You")
    .replace(/\bMe\b/g, "you")
    .replace(/\b(You|you) (was|is|has|does)\b/g, (_, who: string, verb: string) => `${who} ${AGREE[verb]}`);
}

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

/**
 * A server response with its sentences spoken to the person: a claim's `text` (an object with a `claim_id` or a
 * `predicate`), a summary's `value`, a saved assistant message and an answer. Names, fact values, quoted source text
 * and everything else are left exactly as they came.
 */
export function youifyDeep<T>(value: T): T {
  return walk(value as Json) as T;
}

function walk(v: Json): Json {
  if (Array.isArray(v)) return v.map(walk);
  if (v === null || typeof v !== "object") return v;
  const claim = "claim_id" in v || "predicate" in v;
  const chat = v.role === "assistant";
  const out: { [key: string]: Json } = {};
  for (const [k, x] of Object.entries(v)) {
    const sentence = typeof x === "string" && (
      k === "answer" || k === "uncertainty_note" || (k === "text" && (claim || chat)) || (k === "value" && v.predicate === "summary_of"));
    out[k] = sentence ? youify(x as string) : walk(x);
  }
  return out;
}

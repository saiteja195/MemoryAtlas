// Small pure helpers for the chat thread.
import type { PromptGroup } from "./suggest";

/** App keeps questions newest first; a chat reads oldest first. */
export function oldestFirst<T>(items: readonly T[]): T[] {
  return [...items].reverse();
}

/**
 * While an answer is pending, the panel shows three steps. They advance on elapsed time only:
 * the server reports no per-step progress, and the labels must not claim more than that.
 */
export const PHASES = ["Understanding the question", "Searching your memories", "Checking the answer"] as const;

export function phaseAt(elapsedMs: number): 0 | 1 | 2 {
  return elapsedMs < 1500 ? 0 : elapsedMs < 4000 ? 1 : 2;
}

/** Suggested next questions: the first prompts in group order that were not already asked. */
export function followUps(asked: readonly string[], groups: readonly PromptGroup[], max = 3): string[] {
  const seen = new Set(asked.map((q) => q.trim().toLowerCase()));
  const out: string[] = [];
  for (const g of groups) {
    for (const p of g.prompts) {
      if (out.length >= max) return out;
      if (!seen.has(p.trim().toLowerCase())) out.push(p);
    }
  }
  return out;
}

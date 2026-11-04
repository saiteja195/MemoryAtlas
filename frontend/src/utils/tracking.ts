// Opt-in object tracking for a video: the person names up to three objects, a few frames go to SAM 3.1, and what
// comes back is words about when each object was visible. These helpers are the parts with no network or screen.
import type { TrackedObject } from "../api/types";

export const MAX_PHRASES = 3;
export const FRAMES = 12;
const PER_IMAGE = 0.0025;                         // SAM 3.1: $2.50 per 1,000 images
const PEOPLE = new Set(["person", "people", "man", "men", "woman", "women", "child", "children", "kid", "kids", "boy",
  "girl", "baby", "babies", "face", "faces", "human", "humans", "guy", "lady", "ladies", "toddler", "adult", "adults",
  "wife", "husband", "friend", "mom", "dad", "mother", "father"]);

/** The object words the person typed, or why they cannot be used. An empty list means "do not track". */
export function parsePhrases(text: string): { phrases: string[] } | { error: string } {
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const p = raw.trim().toLowerCase().replace(/\s+/g, " ");
    if (!p) continue;
    if (!/^[a-z0-9][a-z0-9 '-]{1,29}$/.test(p)) return { error: 'Name objects in a few plain words, like "wallet" or "car key".' };
    if (p.split(/[ '-]/).some((w) => PEOPLE.has(w))) return { error: "Object tracking does not follow people." };
    if (!out.includes(p)) out.push(p);
  }
  return out.length > MAX_PHRASES ? { error: `Name up to ${MAX_PHRASES} objects.` } : { phrases: out };
}

/** The most this can cost, in dollars, rounded up to the cent. */
export function trackCost(frames: number, objects: number): string {
  return `$${(Math.ceil(frames * objects * PER_IMAGE * 100 - 1e-9) / 100).toFixed(2)}`;
}

const secs = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

/** One plain line per object. */
export function trackLines(objects: TrackedObject[]): string[] {
  return objects.map((o) => o.found && o.ranges.length
    ? `${o.phrase}: seen ${o.ranges.map((r) => `${secs(r.start_ms)} to ${secs(r.end_ms)}`).join(", ")}`
    : `${o.phrase}: not seen`);
}

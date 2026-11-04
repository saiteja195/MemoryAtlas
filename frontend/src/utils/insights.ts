// Pure helpers for the coverage strip and the model cards, tested without a DOM.
import type { Coverage, ModelRow } from "../api/types";

const DAY_MINUTES = 1440;
/** An instant (one photo) would be zero wide; give it enough to see. */
const MIN_WIDTH = 0.6;

const round1 = (n: number) => Math.round(n * 10) / 10;

/** "HH:MM" to minutes since midnight; "24:00" is the end of the day. NaN when it is not a time. */
function minutesOf(hhmm: string): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm);
  if (!m) return Number.NaN;
  const total = Number(m[1]) * 60 + Number(m[2]);
  return total <= DAY_MINUTES ? total : Number.NaN;
}

function windowMinutes(c: Coverage): [number, number] {
  const [a, b] = c.window ?? [6, 22];
  const lo = Math.max(0, Math.min(a, 24)) * 60;
  const hi = Math.max(lo, Math.min(b, 24) * 60);
  return [lo, hi];
}

/** A stretch of minutes as percent of the window, clipped to it, or null when it falls outside. */
function place(start: number, end: number, w0: number, w1: number): { left: number; width: number } | null {
  if (!Number.isFinite(start) || !Number.isFinite(end) || w1 <= w0) return null;
  const s = Math.max(start, w0), e = Math.min(end, w1);
  // A single instant counts when it lands inside the window; a stretch needs some time inside it.
  if (start === end ? start < w0 || start >= w1 : e <= s) return null;
  const span = w1 - w0;
  let left = round1(((s - w0) / span) * 100);
  const right = round1(((e - w0) / span) * 100);
  let width = round1(right - left);
  if (width < MIN_WIDTH) {
    width = MIN_WIDTH;
    left = Math.min(left, round1(100 - MIN_WIDTH));
  }
  return { left: Math.max(0, left), width };
}

/** Covered stretches as percent of the waking window (left edge and width), clipped to it. */
export function stripBlocks(coverage: Coverage): { left: number; width: number }[] {
  const [w0, w1] = windowMinutes(coverage);
  const out: { left: number; width: number }[] = [];
  for (const sp of coverage.spans ?? []) {
    const b = place(minutesOf(sp.start), minutesOf(sp.end), w0, w1);
    if (b) out.push(b);
  }
  return out;
}

/** "4 h 25 min", "45 min", "1 h", "0 min". Never negative, never fractional. */
export function formatMinutes(n: number): string {
  const total = Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
  const h = Math.floor(total / 60), m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** The dashed box over the longest silence, or null when the day has none. */
export function gapBox(coverage: Coverage): { left: number; width: number; label: string } | null {
  const gap = coverage.longest_gap;
  if (!gap || !(gap.minutes > 0)) return null;
  const [w0, w1] = windowMinutes(coverage);
  const box = place(minutesOf(gap.start), minutesOf(gap.end), w0, w1);
  if (!box) return null;
  return { ...box, label: `${formatMinutes(gap.minutes)} with no memories` };
}

export const hourLabel = (h: number | null): string => (h === null ? "none" : `${String(h).padStart(2, "0")}:00`);

const num = (n: number) => n.toLocaleString("en-US");
const plural = (n: number, one: string, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`;

export type ModelFact = { label: string; value: string; text: string };

/** Key and value rows for a model card. Only what applies: no zeros, no averages for replayed calls. */
export function modelRows(row: ModelRow): ModelFact[] {
  const out: ModelFact[] = [];
  const add = (label: string, value: string, text: string) => out.push({ label, value, text });
  if (row.reading > 0) add("Reading", plural(row.reading, "call"), plural(row.reading, "reading call"));
  if (row.answering > 0) add("Answering", plural(row.answering, "call"), plural(row.answering, "answering call"));
  if (row.photos > 0) add("Photos", num(row.photos), plural(row.photos, "photo"));
  if (row.words_read > 0) add("Words read", num(row.words_read), `${num(row.words_read)} words read`);
  if (row.audio_minutes > 0) add("Audio", `${num(row.audio_minutes)} min`, `${num(row.audio_minutes)} audio minutes`);
  // avg_ms is 0 when nothing ran live, so decide from the counts, not the number.
  if (row.calls - row.cache > 0 && row.avg_ms > 0) {
    add("Average response", `${num(row.avg_ms)} ms`, `${num(row.avg_ms)} ms average response`);
  }
  if (row.cache > 0) add("Replayed, no model call", num(row.cache), `${num(row.cache)} replayed, no model call`);
  return out;
}

/** The same facts as plain sentences, for screen readers and tests. */
export function modelLine(row: ModelRow): string[] {
  return modelRows(row).map((r) => r.text);
}

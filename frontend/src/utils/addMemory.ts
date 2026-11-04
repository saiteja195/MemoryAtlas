// Pure helpers for the Add memory dialog: what a file is, which questions are still open, and
// the body to send when the person presses Save. No DOM here, so all of it is unit tested.
import type { Answers, Draft, LlmMode } from "../api/types";

export type FileKind = "frame" | "audio" | "video";

const AUDIO_EXT = /\.(wav|m4a|mp3|ogg|aac|webm|weba|opus)$/i;
const VIDEO_EXT = /\.(mp4|mov|m4v|webm)$/i;

export function classifyFile(file: { name: string; type: string }): { kind: FileKind } | { unsupported: string } {
  const type = file.type.toLowerCase();
  if (type === "image/jpeg" || type === "image/png") return { kind: "frame" };
  if (type.startsWith("image/")) return { unsupported: "Only JPEG or PNG photos are supported. Convert this one and try again." };
  if (type.startsWith("audio/")) return { kind: "audio" };
  if (type.startsWith("video/")) return { kind: "video" };
  if (!type) {
    if (AUDIO_EXT.test(file.name)) return { kind: "audio" };
    if (VIDEO_EXT.test(file.name)) return { kind: "video" };
    if (/\.jpe?g$|\.png$/i.test(file.name)) return { kind: "frame" };
  }
  return { unsupported: `${type || "This kind of file"} is not supported. Add a photo, a recording, a video or a note.` };
}

export function maxBytes(kind: FileKind): number {
  return { frame: 10, audio: 32, video: 200 }[kind] * 1024 * 1024;
}

/** Photos saved together as one memory, and the most they may weigh in total (the web server takes 100 MB once encoded). */
export const MAX_PHOTOS = 8;
export const MAX_PHOTOS_BYTES = 60 * 1024 * 1024;

/** Something the person added: a photo, a voice recording or a video. */
export type Picked = { kind: FileKind; blob: Blob; name: string; modifiedAt: number };
type FileLike = { name: string; type: string; size: number; lastModified: number };

const same = (a: Picked, b: Picked) => a.name === b.name && a.blob.size === b.blob.size && a.modifiedAt === b.modifiedAt;
const mb = (n: number) => `${Math.round(n / 1048576)} MB`;

/**
 * What the file list holds after the person adds `files`. Up to {MAX_PHOTOS} photos can go together as one memory; a voice
 * recording or a video goes on its own. Photos already added are never dropped silently: adding a recording or video to them
 * is refused with the reason, while a lone recording or video is simply replaced, as before.
 */
export function planAdd(current: Picked[], files: (FileLike & Blob)[]): { sources: Picked[]; error: string | null } {
  if (files.length === 0) return { sources: current, error: null };
  const picked: Picked[] = [];
  let error: string | null = null;
  for (const f of files) {
    const c = classifyFile(f);
    if ("unsupported" in c) { error ??= c.unsupported; continue; }
    if (f.size > maxBytes(c.kind)) { error ??= `${f.name} is ${mb(f.size)}, over the ${mb(maxBytes(c.kind))} limit.`; continue; }
    picked.push({ kind: c.kind, blob: f, name: f.name, modifiedAt: f.lastModified || 0 });
  }
  if (picked.length === 0) return { sources: current, error };
  const photos = picked.filter((p) => p.kind === "frame");
  if (photos.length < picked.length) {
    if (picked.length > 1) return { sources: current, error: "Add photos together, or one voice recording or one video on its own." };
    if (current.some((c) => c.kind === "frame")) {
      return { sources: current, error: "A voice recording or video can't go with photos. Remove the photos first, or save them and add this next." };
    }
    return { sources: picked, error };                      // a lone recording or video replaces the one before it
  }
  const kept = current.every((c) => c.kind === "frame") ? [...current] : [];
  let weight = kept.reduce((n, p) => n + p.blob.size, 0);
  for (const p of photos) {
    if (kept.some((k) => same(k, p))) continue;               // the same file picked twice
    if (kept.length >= MAX_PHOTOS) { error = `You can add up to ${MAX_PHOTOS} photos at once. The rest were left out.`; break; }
    if (weight + p.blob.size > MAX_PHOTOS_BYTES) { error = `Those photos would be over ${mb(MAX_PHOTOS_BYTES)} together. The rest were left out.`; break; }
    kept.push(p);
    weight += p.blob.size;
  }
  return { sources: kept, error };
}

export type AnswerState = {
  when?: string;
  /** undefined: not answered. null: the suggested place was accepted. string: a place the person typed. */
  where?: string | null;
  ownerSpeaker?: string;
  people: Record<string, { name: string; consented: boolean | null }>;
};

/** Ids of the questions that still need an answer before Save is allowed. */
export function unanswered(draft: Draft, a: AnswerState): string[] {
  const open: string[] = [];
  for (const q of draft.questions) {
    if (q.id === "when") {
      if (!a.when) open.push(q.id);
    } else if (q.id === "where_confirm") {
      if (a.where === undefined || (a.where !== null && !a.where.trim())) open.push(q.id);
    } else if (q.id === "where") {
      if (!a.where || !a.where.trim()) open.push(q.id);
    } else if (q.id === "owner_speaker") {
      if (!a.ownerSpeaker) open.push(q.id);
    } else if (q.kind === "consent" && q.ref) {
      if (q.ref === a.ownerSpeaker) continue;         // you do not consent to yourself
      const p = a.people[q.ref];
      const speaks = draft.speakers.includes(q.ref);
      if (!p || p.consented === null || (p.consented && speaks && !p.name.trim())) open.push(q.id);
    }
  }
  return open;
}

export function toCommitBody(draft: Draft, a: AnswerState): { draft_id: string; answers: Answers } {
  const answers: Answers = { people: [] };
  if (a.when) answers.when = a.when;
  if (typeof a.where === "string" && a.where.trim()) answers.where = a.where.trim();
  if (a.ownerSpeaker) answers.owner_speaker = a.ownerSpeaker;
  for (const [ref, p] of Object.entries(a.people)) {
    if (ref === a.ownerSpeaker || p.consented === null) continue;
    const name = p.name.trim();
    answers.people.push(name ? { ref, name, consented: p.consented } : { ref, consented: p.consented });
  }
  return { draft_id: draft.draft_id, answers };
}

/** A file's modified time as naive local ISO seconds, the form the API expects. */
export function localIso(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** Adding memories sends data to Muse, so it runs only on the live client (record mode would cache transcripts). */
export function addAvailability(mode: LlmMode | undefined): { ok: true } | { ok: false; message: string } {
  if (mode === "live") return { ok: true };
  if (mode === undefined) return { ok: false, message: "Checking how the app is running…" };
  return { ok: false, message: `Adding memories needs live Muse, and this app is in ${mode} mode. Run with a model key (see docs/LOCAL_SETUP.md) to turn this on.` };
}

/** The value for the "when" box: the person's own answer, else what Muse or the file gave, to the minute. */
export function whenInputValue(draft: Draft, a: AnswerState): string {
  return (a.when ?? draft.captured_at ?? "").slice(0, 16);
}

/** The objects of a "Seen" row, split into the ones shown at first and the rest the person can open. */
export function splitSeen(value: string, limit = 12): { shown: string[]; rest: string[] } {
  const all = value.split(",").map((s) => s.trim()).filter(Boolean);
  return { shown: all.slice(0, limit), rest: all.slice(limit) };
}

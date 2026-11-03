// Pure helpers for the Add memory dialog: what a file is, which questions are still open, and
// the body to send when the person presses Save. No DOM here, so all of it is unit tested.
import type { Answers, Draft } from "../api/types";

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

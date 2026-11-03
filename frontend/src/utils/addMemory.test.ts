import { describe, expect, it } from "vitest";
import type { Draft, Question } from "../api/types";
import { classifyFile, localIso, maxBytes, toCommitBody, unanswered, type AnswerState } from "./addMemory";

const file = (name: string, type: string) => ({ name, type });

describe("classifyFile", () => {
  it("accepts JPEG and PNG as photos", () => {
    expect(classifyFile(file("a.jpg", "image/jpeg"))).toEqual({ kind: "frame" });
    expect(classifyFile(file("a.png", "image/png"))).toEqual({ kind: "frame" });
  });
  it("accepts WAV, M4A and MP3 as audio (the browser converts them to WAV)", () => {
    expect(classifyFile(file("a.wav", "audio/wav"))).toEqual({ kind: "audio" });
    expect(classifyFile(file("a.m4a", "audio/mp4"))).toEqual({ kind: "audio" });
    expect(classifyFile(file("a.mp3", ""))).toEqual({ kind: "audio" });
  });
  it("accepts MP4 and WebM video", () => {
    expect(classifyFile(file("a.mp4", "video/mp4"))).toEqual({ kind: "video" });
    expect(classifyFile(file("a.webm", "video/webm"))).toEqual({ kind: "video" });
  });
  it("keeps an audio-only WebM recording as audio", () => {
    expect(classifyFile(file("voice.webm", "audio/webm"))).toEqual({ kind: "audio" });
  });
  it("refuses HEIC photos and says what to use instead", () => {
    const r = classifyFile(file("a.heic", "image/heic"));
    expect("unsupported" in r && r.unsupported).toMatch(/JPEG or PNG/);
  });
  it("refuses other files and names the type", () => {
    const r = classifyFile(file("a.pdf", "application/pdf"));
    expect("unsupported" in r && r.unsupported).toMatch(/application\/pdf/);
  });
});

describe("maxBytes", () => {
  it("has a limit per kind", () => {
    expect(maxBytes("frame")).toBe(10 * 1024 * 1024);
    expect(maxBytes("audio")).toBe(32 * 1024 * 1024);
    expect(maxBytes("video")).toBe(200 * 1024 * 1024);
  });
});

const q = (id: string, kind: Question["kind"], extra: Partial<Question> = {}): Question =>
  ({ id, field: "x", prompt: id, kind, options: [], ref: null, ...extra });

const draft = (questions: Question[], extra: Partial<Draft> = {}): Draft => ({
  draft_id: "d1", kind: "audio", fields: [], questions, captured_at: null, lat: null, lon: null,
  place_name: null, text: null, perceptions: [], frame_offsets_ms: [], turns: [], speakers: [], ...extra,
});

const empty: AnswerState = { people: {} };

describe("unanswered", () => {
  it("lists when until it is answered", () => {
    const d = draft([q("when", "datetime")]);
    expect(unanswered(d, empty)).toEqual(["when"]);
    expect(unanswered(d, { ...empty, when: "2026-10-29T12:00" })).toEqual([]);
  });

  it("treats accepting the suggested place (null) as an answer, but not leaving it blank", () => {
    const d = draft([q("where_confirm", "choice", { options: ["Yes", "Different place"] })]);
    expect(unanswered(d, empty)).toEqual(["where_confirm"]);
    expect(unanswered(d, { ...empty, where: null })).toEqual([]);
    expect(unanswered(d, { ...empty, where: "Mikado Ramen" })).toEqual([]);
    expect(unanswered(d, { ...empty, where: "  " })).toEqual(["where_confirm"]);
  });

  it("hides the owner's own consent question", () => {
    const d = draft([q("owner_speaker", "choice", { options: ["A", "B"] }),
      q("person_A", "consent", { ref: "A" }), q("person_B", "consent", { ref: "B" })], { speakers: ["A", "B"] });
    expect(unanswered(d, { ...empty, ownerSpeaker: "A" })).toEqual(["person_B"]);
  });

  it("needs a yes or no, and a name when a speaker consents", () => {
    const d = draft([q("person_B", "consent", { ref: "B" })], { speakers: ["A", "B"] });
    const owner = { ownerSpeaker: "A" };
    expect(unanswered(d, { ...owner, people: {} })).toEqual(["person_B"]);
    expect(unanswered(d, { ...owner, people: { B: { name: "", consented: null } } })).toEqual(["person_B"]);
    expect(unanswered(d, { ...owner, people: { B: { name: "", consented: true } } })).toEqual(["person_B"]);
    expect(unanswered(d, { ...owner, people: { B: { name: "Alex", consented: true } } })).toEqual([]);
    expect(unanswered(d, { ...owner, people: { B: { name: "", consented: false } } })).toEqual([]);
  });

  it("does not need a name for someone who is only visible in the picture", () => {
    const d = draft([q("person_visible1", "consent", { ref: "visible1" })], { kind: "frame" });
    expect(unanswered(d, { people: { visible1: { name: "", consented: true } } })).toEqual([]);
  });
});

describe("toCommitBody", () => {
  it("maps answers and drops unset fields", () => {
    const d = draft([], { speakers: ["A", "B"] });
    const body = toCommitBody(d, {
      when: "2026-10-29T12:00", where: null, ownerSpeaker: "A",
      people: { A: { name: "", consented: true }, B: { name: " Alex ", consented: true } },
    });
    expect(body).toEqual({
      draft_id: "d1",
      answers: {
        when: "2026-10-29T12:00", owner_speaker: "A",
        people: [{ ref: "B", name: "Alex", consented: true }],
      },
    });
  });

  it("sends a typed place and omits people who were never answered", () => {
    const body = toCommitBody(draft([]), { where: "Mikado Ramen", people: { B: { name: "", consented: null } } });
    expect(body.answers).toEqual({ where: "Mikado Ramen", people: [] });
  });
});

describe("localIso", () => {
  it("formats a time as naive local ISO seconds, with no zone", () => {
    const ms = new Date(2026, 9, 29, 12, 42, 10).getTime();      // local time, whatever the machine's zone
    expect(localIso(ms)).toBe("2026-10-29T12:42:10");
  });
  it("pads single digits", () => {
    expect(localIso(new Date(2026, 0, 5, 3, 4, 5).getTime())).toBe("2026-01-05T03:04:05");
  });
});

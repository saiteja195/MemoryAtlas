import { describe, expect, it } from "vitest";
import type { ChatMessage, Graph } from "../api/types";
import { buildSuggestions, dayChip, isLauncherShortcut, mergeHistory, turnsFromHistory, type Turn } from "./assistant";

const node = (id: string, type: string, name: string) => ({ id, type, name, attrs: null });
const GRAPH = {
  nodes: [node("me", "person", "Me"), node("person:alex", "person", "Alex"), node("place:cafe", "place", "Blue Door Café"),
          node("object:wallet", "object", "wallet"), node("episode:1", "episode", "Episode 09:10")],
  edges: [],
} as unknown as Graph;
const base = { graph: GRAPH, goals: [] as never[], todosOpen: 0, selection: null, hasMemories: true };
const all = (s: ReturnType<typeof buildSuggestions>) => s.groups.flatMap((g) => g.prompts);

describe("buildSuggestions", () => {
  it("names the person, place and thing from the graph", () => {
    const prompts = all(buildSuggestions(base));
    expect(prompts).toContain("Where did I leave my wallet?");
    expect(prompts).toContain("Which restaurant did Alex recommend?");
    expect(prompts).toContain("What time was my meeting with Alex?");
    expect(prompts).toContain("Summarise my day.");
    expect(prompts).toContain("Did I promise anyone anything?");
    expect(prompts).toContain("What did the models read today?");
  });

  it("only asks about people, places and things that exist", () => {
    const onlyMe = { nodes: [node("me", "person", "Me")], edges: [] } as unknown as Graph;
    const prompts = all(buildSuggestions({ ...base, graph: onlyMe }));
    expect(prompts.some((p) => /recommend|meeting with|leave my/.test(p))).toBe(false);
    expect(prompts).toContain("Summarise my day.");
  });

  it("has nothing to ask until there is a memory", () => {
    const s = buildSuggestions({ ...base, graph: { nodes: [], edges: [] } as unknown as Graph, hasMemories: false });
    expect(s.empty).toBe("Add a memory to start");
    expect(s.groups).toEqual([]);
    expect(buildSuggestions(base).empty).toBeNull();
  });

  it("puts the group a goal cares about first", () => {
    expect(buildSuggestions({ ...base, goals: ["work_meetings"] }).groups[0].title).toBe("To-dos");
    expect(buildSuggestions({ ...base, goals: ["remember_day"] }).groups[0].title).toBe("Summary");
    expect(buildSuggestions(base).groups.map((g) => g.title)).toEqual(["Facts", "Summary", "To-dos", "About my memory"]);
  });

  it("adds prompts about the selected card, first", () => {
    const s = buildSuggestions({ ...base, selection: { kind: "entity", id: "object:wallet" } });
    expect(s.groups[0].title).toBe("About this");
    expect(s.groups[0].prompts.every((p) => p.includes("wallet"))).toBe(true);
    const person = buildSuggestions({ ...base, selection: { kind: "entity", id: "person:alex" } });
    expect(person.groups[0].prompts).toContain("When did I meet Alex?");
    expect(buildSuggestions({ ...base, selection: { kind: "entity", id: "gone" } }).groups[0].title).not.toBe("About this");
  });

  it("offers the gap question only when the coverage has a gap", () => {
    const gap = buildSuggestions({ ...base, gap: { start: "13:20", end: "17:45" } });
    expect(all(gap)).toContain("What happened between 13:20 and 17:45?");
    expect(all(buildSuggestions(base)).some((p) => p.startsWith("What happened between"))).toBe(false);
  });

  it("never repeats a prompt, keeps each short, and never says Unnamed", () => {
    const odd = { nodes: [node("me", "person", "Me"), node("person:x", "person", "   "), node("place:y", "place", ""),
                          node("object:long", "object", "a " + "very ".repeat(40) + "long thing")], edges: [] } as unknown as Graph;
    const s = buildSuggestions({ ...base, graph: odd, selection: { kind: "entity", id: "person:x" } });
    const prompts = all(s);
    expect(new Set(prompts).size).toBe(prompts.length);
    expect(prompts.every((p) => p.length <= 90)).toBe(true);
    expect(prompts.some((p) => /unnamed/i.test(p))).toBe(false);
  });
});

describe("conversation helpers", () => {
  const msg = (over: Partial<ChatMessage>): ChatMessage => ({
    id: "m", role: "user", text: "", as_of: "2026-10-29", status: null, cited_claim_ids: [], citations: [],
    cited_tools: [], redacted: false, ...over,
  });

  it("turns the saved history into question and answer pairs, newest first", () => {
    const turns = turnsFromHistory([
      msg({ id: "1", role: "user", text: "First?" }),
      msg({ id: "2", role: "assistant", text: "One.", status: "answered", cited_claim_ids: ["c1"] }),
      msg({ id: "3", role: "user", text: "Second?", as_of: "2026-10-30" }),
      msg({ id: "4", role: "assistant", text: "Two.", status: "abstained" }),
    ]);
    expect(turns.map((t) => t.question)).toEqual(["Second?", "First?"]);
    expect(turns[1].answer).toMatchObject({ answer: "One.", status: "answered", cited_claim_ids: ["c1"] });
    expect(turns[0].asOf).toBe("2026-10-30");
  });

  it("keeps a question that has no saved answer, and ignores an answer with no question", () => {
    const turns = turnsFromHistory([msg({ id: "1", role: "assistant", text: "Orphan.", status: "answered" }),
                                    msg({ id: "2", role: "user", text: "Unanswered?" })]);
    expect(turns).toHaveLength(1);
    expect(turns[0].question).toBe("Unanswered?");
    expect(turns[0].answer).toBeUndefined();
  });

  it("says which day a message is about only when it is not the day on screen", () => {
    expect(dayChip("2026-10-29", "2026-10-29")).toBeNull();
    expect(dayChip(null, "2026-10-29")).toBeNull();
    expect(dayChip("2026-10-28", "2026-10-29")).toBe("28 Oct");
    expect(dayChip("2026-12-01", null)).toBe("1 Dec");
    expect(dayChip("not a date", "2026-10-29")).toBeNull();
  });

  it("opens the assistant on Cmd+K or Ctrl+K and nothing else", () => {
    const e = (key: string, o: object = {}) => ({ key, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...o });
    expect(isLauncherShortcut(e("k", { metaKey: true }))).toBe(true);
    expect(isLauncherShortcut(e("K", { ctrlKey: true }))).toBe(true);
    expect(isLauncherShortcut(e("k"))).toBe(false);
    expect(isLauncherShortcut(e("k", { ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isLauncherShortcut(e("j", { metaKey: true }))).toBe(false);
  });
});

describe("mergeHistory", () => {
  const turn = (id: number, question: string, over: Partial<Turn> = {}): Turn => ({ id, question, ...over });

  it("takes the saved conversation as the truth, so redacted answers replace the old ones", () => {
    const local = [turn(2, "Q2", { answer: { answer: "old answer" } as never }), turn(1, "Q1")];
    const saved = [turn(2, "Q2", { answer: { answer: "[removed: this relied on information that was forgotten]" } as never }), turn(1, "Q1")];
    expect(mergeHistory(local, saved)[0].answer?.answer).toMatch(/removed/);
  });

  it("keeps a question that failed and was never saved, newest first", () => {
    const failed = turn(5, "Unsaved?", { error: { text: "down", notRecorded: false } });
    const merged = mergeHistory([failed, turn(1, "Q1")], [turn(1, "Q1")]);
    expect(merged.map((t) => t.question)).toEqual(["Unsaved?", "Q1"]);
  });

  it("never gives two turns the same id, so the thread's keys stay unique", () => {
    const failed = turn(1, "Unsaved?", { error: { text: "down", notRecorded: true } });
    const merged = mergeHistory([failed], [turn(1, "Saved 1"), turn(2, "Saved 2")]);
    expect(new Set(merged.map((t) => t.id)).size).toBe(merged.length);
    expect(new Set(mergeHistory(merged, [turn(1, "Saved 1")]).map((t) => t.id)).size).toBe(2);
  });

  it("copes with nothing on either side", () => {
    expect(mergeHistory([], [])).toEqual([]);
  });
});

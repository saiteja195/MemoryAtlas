import { describe, expect, it } from "vitest";
import type { PromptGroup } from "./suggest";
import { followUps, oldestFirst, PHASES, phaseAt } from "./chat";

const groups: PromptGroup[] = [
  { title: "A", hint: "", prompts: ["Where is my wallet?", "Who is Alex?"] },
  { title: "B", hint: "", prompts: ["What did I eat?", "Which gym?"] },
];

describe("oldestFirst", () => {
  it("reverses a copy and leaves the input alone", () => {
    const input = [3, 2, 1];
    expect(oldestFirst(input)).toEqual([1, 2, 3]);
    expect(input).toEqual([3, 2, 1]);
  });
});

describe("phaseAt", () => {
  it("steps through the three phases on fixed times", () => {
    expect([0, 1499, 1500, 3999, 4000, 60000].map(phaseAt)).toEqual([0, 0, 1, 1, 2, 2]);
  });
  it("has a label per phase", () => {
    expect(PHASES).toHaveLength(3);
  });
});

describe("followUps", () => {
  it("skips questions already asked, ignoring case", () => {
    expect(followUps(["where is my wallet?"], groups)).toEqual(["Who is Alex?", "What did I eat?", "Which gym?"]);
  });
  it("respects the maximum", () => {
    expect(followUps([], groups, 2)).toEqual(["Where is my wallet?", "Who is Alex?"]);
  });
  it("defaults to three", () => {
    expect(followUps([], groups)).toHaveLength(3);
  });
  it("is empty when everything has been asked", () => {
    expect(followUps(groups.flatMap((g) => g.prompts), groups)).toEqual([]);
  });
});

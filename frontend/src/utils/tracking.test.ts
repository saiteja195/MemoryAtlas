import { describe, expect, it } from "vitest";
import { MAX_PHRASES, parsePhrases, trackCost, trackLines } from "./tracking";

describe("parsePhrases", () => {
  it("splits on commas, trims, lower-cases and drops repeats", () => {
    expect(parsePhrases("Glasses,  car key , glasses")).toEqual({ phrases: ["glasses", "car key"] });
  });
  it("means no tracking when empty", () => {
    expect(parsePhrases("  , ")).toEqual({ phrases: [] });
  });
  it("allows at most three objects", () => {
    expect(parsePhrases("a b, c d, e f, g h")).toEqual({ error: `Name up to ${MAX_PHRASES} objects.` });
  });
  it("refuses people and odd characters", () => {
    expect(parsePhrases("my wife, wallet")).toHaveProperty("error");
    expect(parsePhrases("person")).toEqual({ error: "Object tracking does not follow people." });
    expect(parsePhrases("<b>")).toHaveProperty("error");
    expect(parsePhrases("x".repeat(40))).toHaveProperty("error");
  });
});

describe("trackCost", () => {
  it("is frames x objects x $0.0025, rounded up to the cent", () => {
    expect(trackCost(12, 3)).toBe("$0.09");
    expect(trackCost(12, 1)).toBe("$0.03");
    expect(trackCost(1, 1)).toBe("$0.01");
  });
});

describe("trackLines", () => {
  it("says when each object was seen, or that it was not", () => {
    const lines = trackLines([
      { phrase: "glasses", found: true, frames_checked: 6, ranges: [{ start_ms: 3500, end_ms: 7000, hits: 5 }] },
      { phrase: "wallet", found: false, frames_checked: 6, ranges: [] },
    ]);
    expect(lines).toEqual(["glasses: seen 3.5 s to 7.0 s", "wallet: not seen"]);
  });
  it("lists several stretches", () => {
    expect(trackLines([{ phrase: "mouse", found: true, frames_checked: 9, ranges: [
      { start_ms: 0, end_ms: 500, hits: 2 }, { start_ms: 2000, end_ms: 2500, hits: 2 }] }]))
      .toEqual(["mouse: seen 0.0 s to 0.5 s, 2.0 s to 2.5 s"]);
  });
});

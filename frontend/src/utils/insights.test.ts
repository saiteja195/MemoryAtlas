import { describe, expect, it } from "vitest";
import type { Coverage, ModelRow } from "../api/types";
import { formatMinutes, gapBox, modelLine, stripBlocks } from "./insights";

function coverage(over: Partial<Coverage> = {}): Coverage {
  return {
    day: "2026-10-29", window: [6, 22], hours: [], covered_hours: 4, waking_hours: 16, share: 0.25,
    busiest_hour: 12, spans: [
      { start: "09:10", end: "09:30" }, { start: "09:41", end: "10:00" },
      { start: "12:30", end: "13:20" }, { start: "17:45", end: "18:00" },
    ],
    longest_gap: { start: "13:20", end: "17:45", minutes: 265 },
    ...over,
  };
}

const row = (over: Partial<ModelRow> = {}): ModelRow => ({
  model: "m", kind_label: "Reads and answers", calls: 4, photos: 0, words_read: 0, audio_minutes: 0,
  avg_ms: 0, reading: 0, answering: 0, cache: 0, ...over,
});

describe("formatMinutes", () => {
  it.each([[0, "0 min"], [1, "1 min"], [45, "45 min"], [60, "1 h"], [265, "4 h 25 min"], [1440, "24 h"]])(
    "%i -> %s", (n, want) => expect(formatMinutes(n)).toBe(want));
  it("never shows a negative or fractional figure", () => {
    expect(formatMinutes(-5)).toBe("0 min");
    expect(formatMinutes(Number.NaN)).toBe("0 min");
    expect(formatMinutes(44.6)).toBe("45 min");
  });
});

describe("stripBlocks", () => {
  it("places spans as percent of the 06:00 to 22:00 window", () => {
    const lefts = stripBlocks(coverage()).map((b) => b.left);
    expect(lefts).toEqual([19.8, 23, 40.6, 73.4]);
  });
  it("widths are percent of the window too", () => {
    expect(stripBlocks(coverage({ spans: [{ start: "06:00", end: "22:00" }] }))).toEqual([{ left: 0, width: 100 }]);
  });
  it("clips spans that leave the window and drops ones fully outside", () => {
    const blocks = stripBlocks(coverage({ spans: [
      { start: "00:00", end: "07:00" }, { start: "21:00", end: "24:00" },
      { start: "02:00", end: "05:00" }, { start: "23:00", end: "24:00" },
    ] }));
    expect(blocks).toEqual([{ left: 0, width: 6.3 }, { left: 93.8, width: 6.2 }]);
    for (const b of blocks) {
      expect(b.left).toBeGreaterThanOrEqual(0);
      expect(b.width).toBeGreaterThan(0);
      expect(b.left + b.width).toBeLessThanOrEqual(100.0001);
    }
  });
  it("reads 24:00 as the end of the day", () => {
    const [b] = stripBlocks(coverage({ spans: [{ start: "20:00", end: "24:00" }] }));
    expect(b.left).toBe(87.5);
    expect(b.left + b.width).toBeLessThanOrEqual(100.0001);
  });
  it("keeps a single-instant span visible and inside the strip", () => {
    const blocks = stripBlocks(coverage({ spans: [{ start: "21:59", end: "21:59" }, { start: "06:00", end: "06:00" }] }));
    expect(blocks).toHaveLength(2);
    for (const b of blocks) {
      expect(b.width).toBeGreaterThan(0);
      expect(b.left + b.width).toBeLessThanOrEqual(100.0001);
    }
  });
  it("copes with no spans and malformed times", () => {
    expect(stripBlocks(coverage({ spans: [] }))).toEqual([]);
    expect(stripBlocks(coverage({ spans: [{ start: "soon", end: "later" }] }))).toEqual([]);
  });
});

describe("gapBox", () => {
  it("is null with no gap", () => {
    expect(gapBox(coverage({ longest_gap: null }))).toBeNull();
    expect(gapBox(coverage({ longest_gap: { start: "09:00", end: "09:00", minutes: 0 } }))).toBeNull();
  });
  it("labels the longest gap and positions it", () => {
    const g = gapBox(coverage());
    expect(g?.label).toBe("4 h 25 min with no memories");
    expect(g?.left).toBe(45.8);
    expect(g!.left + g!.width).toBeLessThanOrEqual(100.0001);
    expect(g!.width).toBe(27.6);
  });
  it("stays inside the strip when the gap runs to 24:00", () => {
    const g = gapBox(coverage({ longest_gap: { start: "20:00", end: "24:00", minutes: 240 } }))!;
    expect(g.left + g.width).toBeLessThanOrEqual(100.0001);
    expect(g.left).toBeGreaterThanOrEqual(0);
  });
});

describe("modelLine", () => {
  it("shows no token figures and no average when nothing ran live", () => {
    const text = modelLine(row({ calls: 2, cache: 2, avg_ms: 0 })).join(" | ");
    expect(text).not.toMatch(/token/i);
    expect(text).not.toMatch(/ms/);
    expect(text).toContain("2 replayed, no model call");
  });
  it("omits the replayed note when nothing was replayed", () => {
    expect(modelLine(row({ calls: 3, avg_ms: 120 })).join(" ")).not.toMatch(/replayed/);
  });
  it("lists what the model did", () => {
    const lines = modelLine(row({ calls: 4, reading: 2, answering: 2, photos: 2, words_read: 1100, avg_ms: 333, cache: 1 }));
    expect(lines).toContain("2 reading calls");
    expect(lines).toContain("2 answering calls");
    expect(lines).toContain("2 photos");
    expect(lines).toContain("1,100 words read");
    expect(lines).toContain("333 ms average response");
    expect(lines).toContain("1 replayed, no model call");
  });
  it("reports audio minutes for a transcriber", () => {
    expect(modelLine(row({ kind_label: "Transcribes", calls: 2, audio_minutes: 2.3, avg_ms: 500 })))
      .toContain("2.3 audio minutes");
  });
});

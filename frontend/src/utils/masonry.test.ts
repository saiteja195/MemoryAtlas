import { describe, expect, it } from "vitest";
import { rowSpan } from "./masonry";

describe("rowSpan", () => {
  it("counts the thin rows a card covers, including the gap below it", () => {
    expect(rowSpan(100, 4, 12)).toBe(28);      // (100 + 12) / 4
    expect(rowSpan(101, 4, 12)).toBe(29);      // never cuts a card short
  });
  it("covers at least one row, whatever the card measures", () => {
    expect(rowSpan(0, 4, 12)).toBe(3);
    expect(rowSpan(-5, 4, 12)).toBe(3);
    expect(rowSpan(Number.NaN, 4, 12)).toBe(3);
  });
  it("copes with a zero or negative row height by giving one row", () => {
    expect(rowSpan(100, 0, 12)).toBe(1);
  });
});

import { describe, expect, it } from "vitest";
import { difference, lumaSignature, pickDistinct } from "./frames";

const flat = (v: number, n = 4) => Array.from({ length: n }, () => v);

describe("lumaSignature", () => {
  it("turns RGBA pixels into one brightness number each", () => {
    const rgba = new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255, 0, 255, 0, 255]);
    const sig = lumaSignature(rgba);
    expect(sig).toHaveLength(3);
    expect(sig[0]).toBeCloseTo(255, 0);
    expect(sig[1]).toBe(0);
    expect(sig[2]).toBeGreaterThan(100);            // green is bright to the eye
  });
  it("copes with no pixels", () => {
    expect(lumaSignature(new Uint8ClampedArray([]))).toEqual([]);
  });
});

describe("difference", () => {
  it("is the average brightness change, 0 for identical", () => {
    expect(difference(flat(10), flat(10))).toBe(0);
    expect(difference(flat(10), flat(30))).toBe(20);
    expect(difference([], [])).toBe(0);
  });
});

describe("pickDistinct", () => {
  it("keeps one frame of a run of near-identical frames", () => {
    const sigs = [flat(10), flat(11), flat(12), flat(80), flat(81), flat(200)];
    expect(pickDistinct(sigs, 8, 12)).toEqual([0, 3, 5]);
  });
  it("keeps a frame only when it differs from the last one kept, so a slow drift still counts", () => {
    const sigs = [flat(0), flat(8), flat(16), flat(24), flat(32)];
    expect(pickDistinct(sigs, 8, 12)).toEqual([0, 2, 4]);
  });
  it("thins an over-full pick evenly down to the limit, keeping the first and the last", () => {
    const sigs = Array.from({ length: 10 }, (_, i) => flat(i * 50));
    expect(pickDistinct(sigs, 4, 12)).toEqual([0, 3, 6, 9]);
  });
  it("sends one frame for a still clip and nothing for no frames", () => {
    expect(pickDistinct([flat(5), flat(5), flat(5)], 8, 12)).toEqual([0]);
    expect(pickDistinct([], 8, 12)).toEqual([]);
  });
});

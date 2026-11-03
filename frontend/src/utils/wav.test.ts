import { describe, expect, it } from "vitest";
import { downmixToMono, encodeWav16, frameOffsets, resampleLinear } from "./wav";

const ascii = (b: Uint8Array, at: number, n: number) => String.fromCharCode(...b.slice(at, at + n));

describe("encodeWav16", () => {
  it("writes a valid mono 16-bit header", () => {
    const wav = encodeWav16(new Float32Array(100), 16000);
    const v = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
    expect(ascii(wav, 0, 4)).toBe("RIFF");
    expect(ascii(wav, 8, 4)).toBe("WAVE");
    expect(ascii(wav, 36, 4)).toBe("data");
    expect(v.getUint16(20, true)).toBe(1);        // PCM
    expect(v.getUint16(22, true)).toBe(1);        // mono
    expect(v.getUint32(24, true)).toBe(16000);    // sample rate
    expect(v.getUint16(34, true)).toBe(16);       // bits
    expect(v.getUint32(40, true)).toBe(200);      // data bytes = samples * 2
    expect(wav.length).toBe(44 + 200);
    expect(v.getUint32(4, true)).toBe(wav.length - 8);
  });

  it("clips samples outside [-1, 1]", () => {
    const wav = encodeWav16(Float32Array.of(2, -2, 0.5), 16000);
    const v = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
    expect(v.getInt16(44, true)).toBe(32767);
    expect(v.getInt16(46, true)).toBe(-32768);
    expect(v.getInt16(48, true)).toBe(16383);   // 0.5 * 32767, truncated
  });
});

describe("downmixToMono", () => {
  it("averages the channels", () => {
    const out = downmixToMono([Float32Array.of(1, 0), Float32Array.of(0, 1)]);
    expect(Array.from(out)).toEqual([0.5, 0.5]);
  });
  it("returns a single channel unchanged", () => {
    expect(Array.from(downmixToMono([Float32Array.of(0.25, -0.25)]))).toEqual([0.25, -0.25]);
  });
});

describe("resampleLinear", () => {
  it("halves the length when the rate doubles", () => {
    expect(resampleLinear(new Float32Array(48000), 48000, 24000).length).toBe(24000);
  });
  it("is the identity at the same rate", () => {
    const s = Float32Array.of(0.1, 0.2, 0.3);
    expect(Array.from(resampleLinear(s, 16000, 16000))).toEqual(Array.from(s));
  });
  it("interpolates between samples", () => {
    const out = resampleLinear(Float32Array.of(0, 1), 1, 2);
    expect(out.length).toBe(4);
    expect(out[0]).toBe(0);
    expect(out[1]).toBeCloseTo(0.5, 5);
  });
});

describe("frameOffsets", () => {
  it("spreads frames inside the clip, sorted, never at 0 or the end", () => {
    const o = frameOffsets(10000, 4);
    expect(o).toEqual([...o].sort((a, b) => a - b));
    expect(o[0]).toBeGreaterThan(0);
    expect(o[o.length - 1]).toBeLessThan(10000);
    expect(o).toHaveLength(4);
  });
  it("takes the midpoint for a single frame", () => {
    expect(frameOffsets(8000, 1)).toEqual([4000]);
  });
});

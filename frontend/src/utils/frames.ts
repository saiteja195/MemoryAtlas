// Choosing which frames of a video are worth sending to Muse. Every frame sent is a paid, slow model call, so near
// duplicates (a camera held still) are dropped here, in the browser, for free. The pixel work needs a canvas; these
// helpers take plain numbers so they can be tested.

/** One brightness number (0 to 255) for each RGBA pixel. */
export function lumaSignature(rgba: Uint8ClampedArray): number[] {
  const out: number[] = [];
  for (let i = 0; i + 2 < rgba.length; i += 4) out.push(0.299 * rgba[i] + 0.587 * rgba[i + 1] + 0.114 * rgba[i + 2]);
  return out;
}

/** The average change in brightness between two signatures: 0 for the same picture, up to 255. */
export function difference(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  if (n === 0) return 0;
  let sum = 0;
  for (let i = 0; i < n; i++) sum += Math.abs(a[i] - b[i]);
  return sum / n;
}

/**
 * Indices of the frames to send, in order. A frame is kept when it differs enough from the last one kept, so a slow
 * pan still yields frames but a still camera yields one. If more than `max` survive they are thinned evenly,
 * keeping the first and the last.
 */
export function pickDistinct(signatures: number[][], max: number, threshold: number): number[] {
  const kept: number[] = [];
  signatures.forEach((sig, i) => {
    if (kept.length === 0 || difference(signatures[kept[kept.length - 1]], sig) >= threshold) kept.push(i);
  });
  if (kept.length <= max) return kept;
  if (max <= 1) return kept.slice(0, 1);
  return Array.from({ length: max }, (_, k) => kept[Math.round((k * (kept.length - 1)) / (max - 1))]);
}

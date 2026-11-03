// Pure audio helpers. The speech service takes only mono 16-bit PCM WAV at 16 or 24 kHz, and
// browsers record webm/opus or mp4/aac, so the conversion happens here before upload.

export function downmixToMono(channels: Float32Array[]): Float32Array {
  if (channels.length === 1) return Float32Array.from(channels[0]);
  const out = new Float32Array(channels[0].length);
  for (const ch of channels) for (let i = 0; i < out.length; i++) out[i] += ch[i] / channels.length;
  return out;
}

export function resampleLinear(samples: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return samples;
  const length = Math.round((samples.length * toRate) / fromRate);
  const out = new Float32Array(length);
  const step = fromRate / toRate;
  for (let i = 0; i < length; i++) {
    const at = i * step;
    const lo = Math.floor(at);
    const hi = Math.min(lo + 1, samples.length - 1);
    out[i] = samples[lo] + (samples[hi] - samples[lo]) * (at - lo);
  }
  return out;
}

export function encodeWav16(samples: Float32Array, sampleRate: number): Uint8Array {
  const bytes = new Uint8Array(44 + samples.length * 2);
  const v = new DataView(bytes.buffer);
  const text = (at: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i)); };
  text(0, "RIFF");
  v.setUint32(4, bytes.length - 8, true);
  text(8, "WAVE");
  text(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);                 // PCM
  v.setUint16(22, 1, true);                 // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);    // byte rate
  v.setUint16(32, 2, true);                 // block align
  v.setUint16(34, 16, true);                // bits per sample
  text(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return bytes;
}

/** Evenly spaced moments strictly inside a clip: never the first frame (often black) or the last. */
export function frameOffsets(durationMs: number, count: number): number[] {
  return Array.from({ length: count }, (_, i) => Math.round((durationMs * (i + 1)) / (count + 1)));
}

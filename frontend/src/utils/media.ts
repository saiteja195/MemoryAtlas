// Browser glue for recordings and uploads: decode audio to WAV, pull frames out of a video, and
// base64-encode for the API. These need a real browser (AudioContext, <video>, canvas), so they
// are exercised by hand and kept thin; the maths lives in wav.ts, which is unit tested.
import { downmixToMono, encodeWav16, frameOffsets, resampleLinear } from "./wav";

export const ASR_RATE = 16000;
const MAX_AUDIO_SECONDS = 600;
const MAX_FRAME_SIDE = 1280;

export function toBase64(data: Blob | Uint8Array): Promise<string> {
  const blob = data instanceof Blob ? data : new Blob([data as BlobPart]);
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(new Error("Could not read the file."));
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.readAsDataURL(blob);
  });
}

export async function toWav16k(blob: Blob): Promise<Uint8Array> {
  const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    if (decoded.duration > MAX_AUDIO_SECONDS) throw new Error("The audio is longer than 10 minutes.");
    const channels = Array.from({ length: decoded.numberOfChannels }, (_, i) => decoded.getChannelData(i));
    const mono = resampleLinear(downmixToMono(channels), decoded.sampleRate, ASR_RATE);
    return encodeWav16(mono, ASR_RATE);
  } catch (e) {
    if (e instanceof Error && /10 minutes/.test(e.message)) throw e;
    throw new Error("This browser could not read that audio. Record again, or choose a WAV file.");
  } finally {
    void ctx.close();
  }
}

function once(target: EventTarget, ok: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const done = () => { target.removeEventListener(ok, done); target.removeEventListener("error", fail); resolve(); };
    const fail = () => { target.removeEventListener(ok, done); target.removeEventListener("error", fail); reject(new Error("The video could not be read.")); };
    target.addEventListener(ok, done);
    target.addEventListener("error", fail);
  });
}

/** MediaRecorder files report an infinite duration until the end has been seen once. */
async function settledDuration(video: HTMLVideoElement): Promise<number> {
  if (Number.isFinite(video.duration)) return video.duration;
  const seen = once(video, "timeupdate");
  video.currentTime = 1e101;
  await seen;
  const d = video.duration;
  video.currentTime = 0;
  return d;
}

export type ExtractedVideo = { frames: Blob[]; offsetsMs: number[]; audio: Uint8Array | null; durationMs: number };

export async function extractVideo(blob: Blob, maxFrames = 4, withAudio = true): Promise<ExtractedVideo> {
  const url = URL.createObjectURL(blob);
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  try {
    const loaded = once(video, "loadedmetadata");
    video.src = url;
    await loaded;
    const durationMs = Math.round((await settledDuration(video)) * 1000);
    const offsetsMs = frameOffsets(durationMs, maxFrames);
    const scale = Math.min(1, MAX_FRAME_SIDE / Math.max(video.videoWidth, video.videoHeight, 1));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const g = canvas.getContext("2d");
    if (!g) throw new Error("This browser cannot read video frames.");
    const frames: Blob[] = [];
    for (const at of offsetsMs) {
      const seeked = once(video, "seeked");
      video.currentTime = at / 1000;
      await seeked;
      g.drawImage(video, 0, 0, canvas.width, canvas.height);
      const jpeg = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/jpeg", 0.85));
      if (!jpeg) throw new Error("Could not capture a frame from the video.");
      frames.push(jpeg);
    }
    let audio: Uint8Array | null = null;
    if (withAudio) try { audio = await toWav16k(blob); } catch { /* no audio track, or one we cannot decode */ }
    return { frames, offsetsMs, audio, durationMs };
  } finally {
    URL.revokeObjectURL(url);
    video.removeAttribute("src");
    video.load();
  }
}

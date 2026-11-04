import { useCallback, useEffect, useRef, useState } from "react";
import {
  captureSupport, describeMediaError, MAX_SECONDS, pickRecorderMime, startGuard, type CaptureKind,
} from "../utils/capture";

export type Captured = { kind: CaptureKind; blob: Blob; name: string };

type Props = { disabled: boolean; onCaptured: (c: Captured) => void };

type Phase = "idle" | "starting" | "live" | "recording" | "review";

const LABEL: Record<CaptureKind, string> = { photo: "Take photo", voice: "Record voice", video: "Record video" };
const FALLBACK: Record<CaptureKind, { accept: string; capture?: string }> = {
  photo: { accept: "image/*", capture: "environment" },
  voice: { accept: "audio/*", capture: "" },
  video: { accept: "video/*", capture: "environment" },
};

const clockText = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/**
 * Take a photo or record voice or video with the device camera and microphone. Permission is
 * asked only when a button is pressed. Every exit path stops the tracks so the camera light goes
 * off. Where the page is not a secure context (plain http on a phone), the buttons become file
 * pickers with capture hints, which open the phone's own camera or recorder.
 */
export function CaptureButtons({ disabled, onCaptured }: Props) {
  const [kind, setKind] = useState<CaptureKind | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [review, setReview] = useState<{ url: string; blob: Blob; name: string } | null>(null);

  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const video = useRef<HTMLVideoElement>(null);
  const timer = useRef<number>(0);
  const raf = useRef<number>(0);
  const audioCtx = useRef<AudioContext | null>(null);
  const reviewUrl = useRef<string | null>(null);
  const guard = useRef(startGuard());

  const env = {
    isSecureContext: typeof window !== "undefined" && window.isSecureContext,
    hasMediaDevices: typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
    hasMediaRecorder: typeof MediaRecorder !== "undefined",
  };
  const support = captureSupport(env);
  const photoSupport = captureSupport({ ...env, hasMediaRecorder: true });

  /** Stop the camera and microphone, the timer and the level meter. Safe to call twice. */
  const release = useCallback(() => {
    window.clearInterval(timer.current);
    cancelAnimationFrame(raf.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void audioCtx.current?.close().catch(() => undefined);
    audioCtx.current = null;
    if (video.current) video.current.srcObject = null;
    setLevel(0);
  }, []);

  const dropReview = useCallback(() => {
    if (reviewUrl.current) URL.revokeObjectURL(reviewUrl.current);
    reviewUrl.current = null;
    setReview(null);
  }, []);

  useEffect(() => () => {
    guard.current.cancel();                  // a permission prompt that resolves after this must not keep the camera
    if (recorder.current) recorder.current.onstop = null;
    if (recorder.current?.state === "recording") recorder.current.stop();
    release();
    if (reviewUrl.current) URL.revokeObjectURL(reviewUrl.current);
  }, [release]);

  const finish = (k: CaptureKind, blob: Blob, ext: string) => {
    release();
    const name = `${k}-${new Date().toISOString().replace(/[:.]/g, "-")}.${ext}`;
    const url = URL.createObjectURL(blob);
    reviewUrl.current = url;
    setReview({ url, blob, name });
    setPhase("review");
  };

  const meter = (s: MediaStream) => {
    try {
      const ctx = new AudioContext();
      audioCtx.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      ctx.createMediaStreamSource(s).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(Math.min(1, peak / 64));
        raf.current = requestAnimationFrame(tick);
      };
      tick();
    } catch { /* the meter is a nicety */ }
  };

  const start = async (k: CaptureKind, face = facing) => {
    setError(null);
    dropReview();
    setKind(k);
    setPhase("starting");
    const mine = guard.current.begin();
    try {
      const s = await navigator.mediaDevices.getUserMedia(
        k === "voice" ? { audio: true } : { video: { facingMode: face }, audio: k === "video" });
      if (!guard.current.isCurrent(mine)) { s.getTracks().forEach((t) => t.stop()); return; }
      stream.current = s;
      if (k !== "voice" && video.current) {
        video.current.srcObject = s;
        await video.current.play().catch(() => undefined);
      }
      if (k === "voice") meter(s);
      setPhase("live");
    } catch (e) {
      if (!guard.current.isCurrent(mine)) return;
      release();
      setKind(null);
      setPhase("idle");
      setError(describeMediaError(e instanceof DOMException || e instanceof Error ? e.name : "", k));
    }
  };

  const cancel = () => {
    guard.current.cancel();
    if (recorder.current?.state === "recording") { recorder.current.onstop = null; recorder.current.stop(); }
    release();
    dropReview();
    setKind(null);
    setPhase("idle");
  };

  const snap = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")?.drawImage(v, 0, 0);
    canvas.toBlob((b) => { if (b) finish("photo", b, "jpg"); }, "image/jpeg", 0.9);
  };

  const record = (k: "voice" | "video") => {
    const s = stream.current;
    if (!s) return;
    const mime = pickRecorderMime((m) => MediaRecorder.isTypeSupported(m), k);
    const rec = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
    rec.onstop = () => {
      const type = rec.mimeType || mime || (k === "voice" ? "audio/webm" : "video/webm");
      finish(k, new Blob(chunks.current, { type }), type.includes("mp4") ? "mp4" : "webm");
    };
    recorder.current = rec;
    rec.start(1000);
    setSeconds(0);
    setPhase("recording");
    const began = Date.now();
    timer.current = window.setInterval(() => {
      const s2 = Math.floor((Date.now() - began) / 1000);
      setSeconds(s2);
      if (s2 >= MAX_SECONDS[k] && rec.state === "recording") rec.stop();
    }, 250);
  };

  const stopRecording = () => { if (recorder.current?.state === "recording") recorder.current.stop(); };

  const flip = () => {
    const next = facing === "environment" ? "user" : "environment";
    setFacing(next);
    release();
    if (kind) void start(kind, next);
  };

  const use = () => {
    if (!review || !kind) return;
    onCaptured({ kind, blob: review.blob, name: review.name });
    dropReview();
    setKind(null);
    setPhase("idle");
  };

  const picked = (k: CaptureKind) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) onCaptured({ kind: k, blob: f, name: f.name });
  };

  const kinds: CaptureKind[] = ["photo", "voice", "video"];
  const busy = phase !== "idle";

  return (
    <div className="capture" role="group" aria-label="Capture with your device">
      {!busy && (
        <div className="capture-buttons">
          {kinds.map((k) => {
            const live = k === "photo" ? photoSupport.ok : support.ok;
            if (live) {
              return <button type="button" className="btn" key={k} disabled={disabled} onClick={() => void start(k)}>{LABEL[k]}</button>;
            }
            const fb = FALLBACK[k];
            return (
              <label className={`btn${disabled ? " disabled" : ""}`} key={k}>
                {LABEL[k]}
                <input type="file" className="sr-only" accept={fb.accept} capture={fb.capture as "environment" | undefined}
                       disabled={disabled} onChange={picked(k)} />
              </label>
            );
          })}
        </div>
      )}

      {!busy && !support.ok && <p className="small muted" id="capture-why">{support.message}</p>}
      {error && <div className="notice error" role="alert">{error}</div>}

      {busy && kind && (
        <div className="capture-surface" aria-live="polite">
          {kind !== "voice" && phase !== "review" && (
            <video ref={video} className="capture-video" muted playsInline aria-label="Camera preview" />
          )}
          {kind === "voice" && phase !== "review" && (
            <div className="capture-meter" aria-hidden="true"><i style={{ transform: `scaleX(${0.05 + level * 0.95})` }} /></div>
          )}
          {phase === "starting" && <p className="small muted">Waiting for permission…</p>}
          {phase === "recording" && (
            <p className="small"><span className="rec-dot" aria-hidden="true" /> Recording {clockText(seconds)} of {clockText(MAX_SECONDS[kind as "voice" | "video"])}</p>
          )}

          {phase === "review" && review && (
            <div className="capture-review">
              {kind === "photo" && <img src={review.url} alt="The photo you took" />}
              {kind === "voice" && <audio src={review.url} controls />}
              {kind === "video" && <video src={review.url} controls playsInline className="capture-video" />}
            </div>
          )}

          <div className="row">
            {phase === "live" && kind === "photo" && (
              <>
                <button type="button" className="btn primary" onClick={snap}>Capture</button>
                <button type="button" className="btn ghost" onClick={flip}>Flip camera</button>
              </>
            )}
            {phase === "live" && kind === "video" && (
              <>
                <button type="button" className="btn primary" onClick={() => record("video")}>Start recording</button>
                <button type="button" className="btn ghost" onClick={flip}>Flip camera</button>
              </>
            )}
            {phase === "live" && kind === "voice" && (
              <button type="button" className="btn primary" onClick={() => record("voice")}>Start recording</button>
            )}
            {phase === "recording" && <button type="button" className="btn primary" onClick={stopRecording}>Stop</button>}
            {phase === "review" && (
              <>
                <button type="button" className="btn primary" onClick={use}>Use this</button>
                <button type="button" className="btn" onClick={() => void start(kind)}>Retake</button>
              </>
            )}
            <button type="button" className="btn ghost" onClick={cancel}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

// Rules for using the camera and microphone. Pure, so the wording and the choices are tested;
// the component that calls getUserMedia is thin.

export type CaptureKind = "photo" | "voice" | "video";

export const MAX_SECONDS: Record<"voice" | "video", number> = { voice: 600, video: 60 };

type Env = { isSecureContext: boolean; hasMediaDevices: boolean; hasMediaRecorder: boolean };

export type Support =
  | { ok: true }
  | { ok: false; reason: "insecure" | "no-devices" | "no-recorder"; message: string };

export function captureSupport(env: Env): Support {
  if (!env.isSecureContext) {
    return { ok: false, reason: "insecure",
      message: "Camera and microphone only work on a secure page. Open this site over https, or use the buttons below to pick or take a file." };
  }
  if (!env.hasMediaDevices) {
    return { ok: false, reason: "no-devices", message: "This browser cannot reach a camera or microphone." };
  }
  if (!env.hasMediaRecorder) {
    return { ok: false, reason: "no-recorder", message: "This browser cannot record audio or video." };
  }
  return { ok: true };
}

export function describeMediaError(name: string, kind: CaptureKind): string {
  const device = kind === "voice" ? "microphone" : "camera";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return `Permission to use the ${device} was blocked. Allow it in your browser's site settings for this page, then try again.`;
    case "NotFoundError":
    case "DevicesNotFoundError":
      return `No ${device} was found on this device.`;
    case "NotReadableError":
    case "TrackStartError":
      return `The ${device} is being used by another app. Close it and try again.`;
    default:
      return `Could not start the ${device}. Try again.`;
  }
}

const MIMES = {
  voice: ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"],
  video: ["video/webm;codecs=vp9,opus", "video/webm", "video/mp4"],
} as const;

export function pickRecorderMime(isSupported: (mime: string) => boolean, kind: "voice" | "video"): string | undefined {
  return MIMES[kind].find(isSupported);
}

/**
 * getUserMedia can resolve long after the person gave up (Cancel, or the dialog closing, while the
 * permission prompt was open). A start is only current until the next start or a cancel; a stale one
 * must stop the stream it receives, or the camera light stays on.
 */
export function startGuard() {
  let n = 0;
  return { begin: () => ++n, cancel: () => { n++; }, isCurrent: (id: number) => id === n };
}

import { describe, expect, it } from "vitest";
import { captureSupport, describeMediaError, MAX_SECONDS, pickRecorderMime } from "./capture";

const ok = { isSecureContext: true, hasMediaDevices: true, hasMediaRecorder: true };

describe("captureSupport", () => {
  it("is ok when the page is secure and the browser has the APIs", () => {
    expect(captureSupport(ok)).toEqual({ ok: true });
  });
  it("explains https when the page is not a secure context", () => {
    const r = captureSupport({ ...ok, isSecureContext: false, hasMediaDevices: false });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.reason).toBe("insecure");
      expect(r.message).toMatch(/https/);
    }
  });
  it("reports a browser with no camera or microphone API", () => {
    const r = captureSupport({ ...ok, hasMediaDevices: false });
    expect(r.ok === false && r.reason).toBe("no-devices");
  });
  it("reports a browser that cannot record", () => {
    const r = captureSupport({ ...ok, hasMediaRecorder: false });
    expect(r.ok === false && r.reason).toBe("no-recorder");
  });
});

describe("describeMediaError", () => {
  it("tells the person how to re-allow a denied permission", () => {
    expect(describeMediaError("NotAllowedError", "photo")).toMatch(/site settings/i);
  });
  it("names the device that was not found", () => {
    expect(describeMediaError("NotFoundError", "voice")).toMatch(/microphone/i);
    expect(describeMediaError("NotFoundError", "video")).toMatch(/camera/i);
  });
  it("says when another app is using the device", () => {
    expect(describeMediaError("NotReadableError", "photo")).toMatch(/another app/i);
  });
  it("falls back to a generic retry message", () => {
    expect(describeMediaError("SomethingElse", "voice")).toMatch(/try again/i);
  });
});

describe("limits and formats", () => {
  it("caps voice at 10 minutes and video at 60 seconds", () => {
    expect(MAX_SECONDS).toEqual({ voice: 600, video: 60 });
  });
  it("picks the first supported recorder type", () => {
    expect(pickRecorderMime((m) => m === "audio/mp4", "voice")).toBe("audio/mp4");
    expect(pickRecorderMime(() => true, "voice")).toBe("audio/webm;codecs=opus");
    expect(pickRecorderMime((m) => m === "video/mp4", "video")).toBe("video/mp4");
  });
  it("returns undefined when nothing is supported", () => {
    expect(pickRecorderMime(() => false, "video")).toBeUndefined();
  });
});

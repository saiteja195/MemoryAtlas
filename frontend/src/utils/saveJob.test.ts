import { describe, expect, it } from "vitest";
import type { SaveJob } from "../api/types";
import { ApiError } from "../api/client";
import { pollJob, progressText } from "./saveJob";

const job = (over: Partial<SaveJob> = {}): SaveJob => ({
  job_id: "j", state: "running", elapsed_s: 0, calls_started: 0, calls_done: 0, working_s: 0, result: null, error: null, ...over,
});

describe("progressText", () => {
  it("starts quietly, then says Muse is working with the step and the time", () => {
    expect(progressText(null).title).toBe("Starting…");
    expect(progressText(job()).title).toBe("Starting…");
    const t = progressText(job({ calls_started: 2, calls_done: 1, working_s: 12.3, elapsed_s: 40 }));
    expect(t.title).toBe("Muse is working…");
    expect(t.detail).toContain("Step 2");
    expect(t.detail).toContain("12 s");
    expect(t.detail).toContain("40 s so far");
  });
  it("does not say the same number of seconds twice", () => {
    const first = progressText(job({ calls_started: 1, working_s: 24.2, elapsed_s: 24.4 }));
    expect(first.detail).toBe("Step 1 · 24 s");
    const later = progressText(job({ calls_started: 2, calls_done: 1, working_s: 5, elapsed_s: 24 }));
    expect(later.detail).toBe("Step 2 · 5 s · 24 s so far");
  });
  it("says what is happening between two model calls", () => {
    expect(progressText(job({ calls_started: 1, calls_done: 1, elapsed_s: 15 })).title).toBe("Saving what Muse found…");
  });
  it("is honest when it is slow, and says the person can leave", () => {
    const slow = progressText(job({ calls_started: 1, working_s: 50, elapsed_s: 60 }));
    expect(slow.detail).toMatch(/slower than usual/i);
    const long = progressText(job({ calls_started: 1, working_s: 95, elapsed_s: 100 }));
    expect(long.detail).toMatch(/keep saving/i);
  });
  it("shows minutes for long waits", () => {
    expect(progressText(job({ calls_started: 1, working_s: 75, elapsed_s: 130 })).detail).toContain("2 min 10 s so far");
  });
});

describe("pollJob", () => {
  const instant = { intervalMs: 0, sleep: async () => undefined };

  it("polls until the save is done and returns the result", async () => {
    const seen: string[] = [];
    const replies = [job(), job({ calls_started: 1 }), job({ state: "done", result: { session_id: "s", results: [], grants: [] } })];
    const result = await pollJob(async () => replies.shift()!, (j) => seen.push(j.state), instant);
    expect(result.session_id).toBe("s");
    expect(seen).toEqual(["running", "running", "done"]);
  });

  it("throws the server's reason when the save failed", async () => {
    const failed = job({ state: "error", error: { status: 503, message: "the model API is down" } });
    await expect(pollJob(async () => failed, () => undefined, instant)).rejects.toMatchObject({ status: 503, message: "the model API is down" });
    await expect(pollJob(async () => failed, () => undefined, instant)).rejects.toBeInstanceOf(ApiError);
  });

  it("rides out a brief network blip but gives up after several in a row", async () => {
    let n = 0;
    const flaky = async () => { n++; if (n <= 2) throw new Error("offline"); return job({ state: "done", result: { session_id: "ok", results: [], grants: [] } }); };
    expect((await pollJob(flaky, () => undefined, instant)).session_id).toBe("ok");
    await expect(pollJob(async () => { throw new Error("offline"); }, () => undefined, instant)).rejects.toThrow(/offline/);
  });

  it("gives up with a clear message when it takes far too long", async () => {
    let t = 0;
    const clock = { ...instant, now: () => (t += 60_000), maxMs: 5 * 60_000 };
    await expect(pollJob(async () => job(), () => undefined, clock)).rejects.toThrow(/taking too long/i);
  });
});

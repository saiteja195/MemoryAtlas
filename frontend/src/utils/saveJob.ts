// Saving a memory runs in the background: the page starts it, then polls until it is done. These helpers say what to
// show while Muse works and do the polling, with the clock and the waiting injected so they can be tested.
import { ApiError } from "../api/client";
import type { CommitResult, SaveJob } from "../api/types";

/** "12 s", or "2 min 10 s" once it is past a minute. */
function span(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/** What to tell the person while a save runs. Honest about time: no invented percentages. */
export function progressText(job: SaveJob | null): { title: string; detail: string } {
  if (!job || job.calls_started === 0) return { title: "Starting…", detail: "" };
  if (job.calls_started === job.calls_done) {
    return { title: "Saving what Muse found…", detail: `${span(job.elapsed_s)} so far` };
  }
  let detail = `Step ${job.calls_started} · ${span(job.working_s)} · ${span(job.elapsed_s)} so far`;
  if (job.working_s >= 90) detail += ". Still working: you can close this and it will keep saving.";
  else if (job.working_s >= 45) detail += ". Slower than usual, but still going.";
  return { title: "Muse is working…", detail };
}

type Options = {
  intervalMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  /** Give up waiting after this long (the server keeps going; the memory may still appear). */
  maxMs?: number;
  /** Consecutive failed polls to ride out (a network blip) before giving up. */
  blips?: number;
};

/** Polls a save until it is done: returns its result, or throws the server's reason if it failed. */
export async function pollJob(
  fetchJob: () => Promise<SaveJob>, onUpdate: (job: SaveJob) => void, options: Options = {},
): Promise<CommitResult> {
  const { intervalMs = 1500, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), now = Date.now, maxMs = 15 * 60_000, blips = 4 } = options;
  const began = now();
  let failures = 0;
  for (;;) {
    let job: SaveJob;
    try {
      job = await fetchJob();
      failures = 0;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) throw e;            // the save is unknown: nothing to wait for
      if (++failures > blips) throw e;
      await sleep(intervalMs);
      continue;
    }
    onUpdate(job);
    if (job.state === "done" && job.result) return job.result;
    if (job.state === "error") throw new ApiError(job.error?.status ?? 500, job.error?.message ?? "Saving failed.");
    if (now() - began > maxMs) {
      throw new Error("Saving is taking too long. Reload in a minute: the memory may still appear.");
    }
    await sleep(intervalMs);
  }
}

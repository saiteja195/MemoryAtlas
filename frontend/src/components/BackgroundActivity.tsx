import { useState } from "react";
import type { CommitResult, Draft, ProcessingJob } from "../api/types";
import { WithdrawCodes } from "./AddMemory";

const NAMES: Record<string, string> = {
  preview: "Reading your upload", save: "Saving your memory", track: "Following objects",
  answer: "Preparing your answer", correction: "Correcting a memory",
};

type Props = { jobs: ProcessingJob[]; error: string | null; onReview: (draft: Draft) => void;
  onDismiss: (id: string) => Promise<void> };

export function BackgroundActivity({ jobs, error, onReview, onDismiss }: Props) {
  const [notice, setNotice] = useState<string | null>(null);
  const active = jobs.filter((j) => j.state === "running" || j.state === "queued").length;
  if (!jobs.length && !error) return null;
  return (
    <details className="background-activity" open>
      <summary>Background activity{active > 0 ? ` · ${active} running` : ""}</summary>
      <p className="small muted">You can close Add Memory and use the app. Accepted work continues if you close this browser tab; check here when you return.</p>
      {(error || notice) && <p className="notice warn" role="status">{error ?? notice}</p>}
      <ul className="activity-list">
        {[...jobs].reverse().map((job) => {
          const running = job.state === "queued" || job.state === "running";
          const saved = job.kind === "save" && job.state === "done" ? job.result as unknown as CommitResult : null;
          return (
            <li key={job.job_id}>
              <div className="activity-row">
                <strong>{NAMES[job.kind ?? "save"] ?? "Processing"}</strong>
                <span className={`chip ${job.state === "error" ? "warn" : job.state === "done" ? "ok" : "accent"}`}>
                  {job.state === "done" ? job.kind === "preview" ? "Ready to review" : "Completed" : job.state === "queued" ? "Queued" : job.state === "error" ? "Needs attention" : `${Math.round(job.elapsed_s)} s`}
                </span>
                {job.kind === "preview" && job.state === "done" && job.result && (
                  <button className="btn small" onClick={() => onReview(job.result as unknown as Draft)}>Review upload</button>
                )}
                {!running && <button className="btn small ghost" aria-label={`Dismiss ${NAMES[job.kind ?? "save"] ?? "processing"}`}
                  onClick={() => void onDismiss(job.job_id).catch(() => setNotice("Could not dismiss this item. Try again."))}>Dismiss</button>}
              </div>
              {running && <p className="small muted" role="status">{job.calls_started ? `${job.calls_done} of ${job.calls_started} model calls finished` : "Waiting to start…"}</p>}
              {job.error && <p className="small" role="alert">{job.error.message}</p>}
              {saved && <>
                <p className="small">{saved.results.some((r) => r.status === "ingested") ? "Your memory is saved." : "Nothing was added; it may be a duplicate or not consented."}</p>
                {saved.results.some((r) => r.compile_rejected) && <p className="small notice warn">Some facts could not be extracted. Review the memory before relying on it.</p>}
                {saved.tracking?.state === "error" && <p className="small notice warn">{saved.tracking.message}</p>}
                {!!saved.grants.length && <details><summary>Consent withdrawal codes</summary><WithdrawCodes grants={saved.grants} /></details>}
              </>}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

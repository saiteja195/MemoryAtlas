import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ProcessingJob } from "../api/types";

/** Lives above dialogs/pages. Reopening the app discovers accepted work from the server. */
export function useMemoryJobs(onChanged: () => void) {
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const seen = useRef(new Set<string>());
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    try {
      const rows = await api.jobs();
      if (!mounted.current) return;
      setJobs(rows);
      setError(null);
      let needsRefresh = false;
      for (const job of rows) {
        if (job.state === "done" && job.kind !== "preview" && !seen.current.has(job.job_id)) {
          seen.current.add(job.job_id);
          needsRefresh = true;
        }
      }
      if (needsRefresh) changed.current();
    } catch {
      if (mounted.current) setError("Cannot check background activity. Accepted work may still be running.");
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      await refresh();
      if (!stopped) timer = setTimeout(tick, document.hidden ? 8000 : 1500);
    };
    void tick();
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { stopped = true; mounted.current = false; clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [refresh]);
  const dismiss = async (id: string) => { await api.dismissJob(id); await refresh(); };
  return { jobs, error, refresh, dismiss };
}

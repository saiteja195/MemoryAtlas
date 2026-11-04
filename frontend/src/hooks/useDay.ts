import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Insights } from "../api/types";

/**
 * The day on screen, shared by the dashboard, the Atlas and the assistant: what the person picked, or the
 * latest day with memories. `insights` is that day's coverage and the models' usage; it is fetched again when
 * `dataKey` changes (the memories changed). A picked day that no longer has memories falls back to the latest.
 */
export function useDay(dataKey: number) {
  const [picked, setPicked] = useState<string | null>(null);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.insights(picked ?? undefined)
      .then((i) => { if (live) { setInsights(i); setError(null); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [picked, dataKey]);

  useEffect(() => {
    if (picked && insights && insights.days.length > 0 && !insights.days.includes(picked)) setPicked(null);
  }, [picked, insights]);

  const day = picked ?? insights?.day ?? null;
  return { day, days: insights?.days ?? [], setDay: setPicked, insights, error };
}

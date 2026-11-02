import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DemoStatus, Graph, Grant, Health, Media, Receipt } from "../api/types";
import { prefersReducedMotion } from "../utils/theme";

export type Notice = { kind: "error" | "warn" | "info"; text: string };

const POLL_MS = 2500;
// After a forgetting, let the graph animate (facts fade, survivors pulse) before the receipt
// covers it. Skipped for people who prefer reduced motion.
const RECEIPT_DELAY_MS = 1500;

/** Everything that comes from the server, plus the actions that change it. */
export function useAtlas() {
  const [health, setHealth] = useState<Health | null>(null);
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [media, setMedia] = useState<Media | null>(null);
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [dataKey, setDataKey] = useState(0);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [offline, setOffline] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [pulse, setPulse] = useState<Set<string>>(new Set());

  const graphSig = useRef("");
  const grantSig = useRef("");
  const shown = useRef<Set<string> | null>(null); // receipts already surfaced
  const timers = useRef<number[]>([]);

  const presentReceipt = useCallback((r: Receipt) => {
    setPulse(new Set(r.retained.map((x) => x.claim_id)));
    const wait = prefersReducedMotion() ? 0 : RECEIPT_DELAY_MS;
    timers.current.push(window.setTimeout(() => setReceipt(r), wait));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [h, s, m, g, gr] = await Promise.all([
        api.health(), api.status(), api.media(), api.graph(), api.grants(),
      ]);
      setHealth(h); setStatus(s); setMedia(m); setGrants(gr); setOffline(false); setLoaded(true);
      grantSig.current = JSON.stringify(gr.map((x) => [x.grant_id, x.revoked_at, x.receipt_id]));
      const sig = JSON.stringify(g);
      if (sig !== graphSig.current) {
        graphSig.current = sig;
        setGraph(g);
        setDataKey((k) => k + 1);
      }
      // Surface receipts we have not shown (including one produced by another browser tab).
      if (shown.current === null) {
        shown.current = new Set(gr.flatMap((x) => (x.receipt_id ? [x.receipt_id] : [])));
      } else {
        for (const x of gr) {
          if (x.receipt_id && !shown.current.has(x.receipt_id)) {
            shown.current.add(x.receipt_id); // claim it first so two refreshes cannot both show it
            presentReceipt(await api.receipt(x.receipt_id));
          }
        }
      }
    } catch {
      setOffline(true);
    }
  }, [presentReceipt]);

  useEffect(() => {
    void refresh();
    // Watch for consent changes made elsewhere (the simulated device in another tab).
    const id = window.setInterval(async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const gr = await api.grants();
        const sig = JSON.stringify(gr.map((x) => [x.grant_id, x.revoked_at, x.receipt_id]));
        if (sig !== grantSig.current) void refresh();
        setOffline(false);
      } catch { setOffline(true); }
    }, POLL_MS);
    return () => { window.clearInterval(id); timers.current.forEach(window.clearTimeout); };
  }, [refresh]);

  /** Run a server action: show what is happening, report failure, then reload everything. */
  const run = useCallback(async <T,>(label: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(label);
    setNotice(null);
    try {
      const out = await fn();
      await refresh();
      return out;
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const advance = useCallback(async (steps: number) => {
    const res = await run("Playing the day", () => api.advance(steps));
    const problems = res?.played.flatMap((p) => p.rejected) ?? [];
    if (problems.length) {
      setNotice({ kind: "warn", text: `Some events could not be turned into memories: ${[...new Set(problems)].join("; ")}` });
    }
  }, [run]);

  const uploadLive = useCallback(
    (id: string) => run("Uploading the photo", () => api.uploadLive(id)), [run]);

  /** Correct or set aside a remembered fact. Returns true when the server accepted it. */
  const correct = useCallback(async (claimId: string, body: { text?: string; retract?: boolean; at?: string }) => {
    const out = await run("Recording the correction", () => api.correct(claimId, body));
    return out !== undefined;
  }, [run]);

  const reset = useCallback(async () => {
    shown.current = new Set();
    setReceipt(null);
    setPulse(new Set());
    await run("Resetting", () => api.reset());
  }, [run]);

  /** Withdraw consent from this window (the simulated device calls this too). */
  const revoke = useCallback(async (grantId: string, token: string): Promise<Receipt> => {
    const r = await api.revoke(grantId, token);
    shown.current?.add(r.receipt_id); // we show it ourselves, below
    await refresh();
    presentReceipt(r);
    return r;
  }, [presentReceipt, refresh]);

  return {
    health, status, media, graph, dataKey, grants, busy, notice, setNotice, offline, loaded,
    receipt, closeReceipt: () => setReceipt(null), openReceipt: (r: Receipt) => setReceipt(r),
    pulse, refresh, advance, uploadLive, correct, reset, revoke,
  };
}

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DemoStatus, Graph, Grant, Health, Media, Receipt } from "../api/types";
import { summarize } from "../utils/dashboard";
import { CATEGORY_INFO, dayCards, formatBytes } from "../utils/graph";
import { personName, sessionLabel } from "./Badges";
import { kindWord } from "./Header";

type Props = {
  graph: Graph;
  status: DemoStatus | null;
  media: Media | null;
  health: Health | null;
  grants: Grant[];
  busy: boolean;
  offline: boolean;
  onPlayNext: () => void;
  onPlayAll: () => void;
  onOpenAtlas: () => void;
  onOpenMoment: (id: string) => void;
  onAsk: (q: string) => void;
  onConsent: () => void;
  onReceipt: (id: string) => void;
  onLive: (id: string) => void;
  onReset: () => void;
};

const SOURCE_COLOR: Record<string, string> = {
  Photo: "var(--s-frame_observation)", Conversation: "var(--s-transcript_segment)", Calendar: "var(--s-calendar_event)",
  Inferred: "var(--s-derivation)", "Confirmed by you": "var(--s-user_confirmation)", Location: "var(--c-place)",
};

function Donut({ parts }: { parts: { label: string; value: number; color: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  const r = 40, c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg className="donut" viewBox="0 0 100 100" role="img"
         aria-label={parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
      <circle cx="50" cy="50" r={r} fill="none" stroke="var(--surface-2)" strokeWidth="14" />
      {total > 0 && parts.filter((p) => p.value > 0).map((p) => {
        const len = (p.value / total) * c;
        const el = (
          <circle key={p.label} cx="50" cy="50" r={r} fill="none" stroke={p.color} strokeWidth="14"
                  strokeDasharray={`${Math.max(len - 1.5, 0)} ${c}`} strokeDashoffset={-offset} transform="rotate(-90 50 50)" />
        );
        offset += len;
        return el;
      })}
      <text x="50" y="48" textAnchor="middle" className="donut-n">{total}</text>
      <text x="50" y="62" textAnchor="middle" className="donut-l">facts</text>
    </svg>
  );
}

function Bars({ rows, colorOf }: { rows: { label: string; count: number }[]; colorOf?: (l: string) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <ul className="bars">
      {rows.map((r) => (
        <li key={r.label}>
          <span className="bar-label">{r.label}</span>
          <span className="bar-track"><span className="bar-fill" style={{ inlineSize: `${(r.count / max) * 100}%`, background: colorOf?.(r.label) ?? "var(--accent)" }} /></span>
          <span className="bar-n">{r.count}</span>
        </li>
      ))}
    </ul>
  );
}

export function Dashboard(p: Props) {
  const s = useMemo(() => summarize(p.graph), [p.graph]);
  const cards = useMemo(() => dayCards(p.graph), [p.graph]);
  const played = p.status?.events.filter((e) => e.played).length ?? 0;
  const total = p.status?.events.length ?? 0;
  const nextEvent = p.status?.events.find((e) => e.id === p.status?.next);
  const live = p.status?.events.filter((e) => e.live_upload && !e.played) ?? [];
  const withdrawn = p.grants.filter((g) => g.revoked_at);
  const active = p.grants.filter((g) => !g.revoked_at);
  const kept = p.media?.raw_media_bytes_retained ?? 0;
  const empty = s.facts === 0;

  // The latest forgetting receipt, summarised here so the outcome of a withdrawal is visible at a glance.
  const lastReceiptId = withdrawn.map((g) => g.receipt_id).filter(Boolean).pop() ?? null;
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  useEffect(() => {
    let cancelled = false;
    setReceipt(null);
    if (lastReceiptId) api.receipt(lastReceiptId).then((r) => { if (!cancelled) setReceipt(r); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [lastReceiptId]);

  const suggestions: { title: string; text: string; action: string; run: () => void; primary?: boolean }[] = [];
  if (nextEvent) suggestions.push({ title: "Play the staged day", text: `Next up: the ${nextEvent.at} ${kindWord(nextEvent.kind, nextEvent.label)}. Each event becomes sourced facts.`, action: "Play next", run: p.onPlayNext, primary: empty });
  if (!empty && withdrawn.length === 0) {
    suggestions.push({ title: "Ask something no single source holds", text: "Which restaurant did Alex recommend? The answer links a chat to a photo of a sign.", action: "Ask it", run: () => p.onAsk("Which restaurant did Alex recommend when we met near the office?"), primary: true });
  }
  if (live.length) suggestions.push({ title: "Watch memory correct itself", text: `Upload the ${live[0].at} photo, then ask where your wallet is. The old answer stays as history.`, action: "Upload photo", run: () => p.onLive(live[0].id) });
  if (!empty && active.length && withdrawn.length === 0) suggestions.push({ title: "Let someone withdraw consent", text: "See what is removed, what is kept and why, with automated leak checks.", action: "Open consent", run: p.onConsent });
  if (withdrawn.length) suggestions.push({ title: "Check what was forgotten", text: "Ask the restaurant question again. It should now say there is no record.", action: "Ask again", run: () => p.onAsk("Which restaurant did Alex recommend when we met near the office?"), primary: true });

  return (
    <div className="dash">
      <section className="dash-hero">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h2>{empty ? "Your memory is empty" : "Your memory at a glance"}</h2>
          <p className="muted">
            {empty ? "Play the staged day to turn photos, a calendar entry and a conversation into sourced facts."
              : `${s.facts} facts across ${s.moments} moments, each traceable to where it came from.`}
          </p>
        </div>
        <div className="dash-actions">
          {nextEvent && <button type="button" className="btn primary large" disabled={p.busy || p.offline} onClick={p.onPlayNext}>Play next · {nextEvent.at}</button>}
          {nextEvent && <button type="button" className="btn large" disabled={p.busy || p.offline} onClick={p.onPlayAll}>Play the day</button>}
          <button type="button" className="btn large" onClick={p.onOpenAtlas}>Open the map</button>
          {!empty && <button type="button" className="btn large ghost" disabled={p.busy} onClick={p.onReset}>Reset</button>}
        </div>
      </section>

      {p.offline && <p className="notice error" role="alert">The backend is not reachable. Start it with <code>make api</code>.</p>}

      <section className="kpis" aria-label="Key numbers">
        <div className="kpi"><span className="kpi-l">Facts remembered</span><b>{s.current}</b><span className="kpi-s">{s.replaced ? `${s.replaced} replaced by newer evidence` : "none replaced yet"}</span></div>
        <div className="kpi"><span className="kpi-l">People, places, things</span><b>{s.people + s.places + s.things}</b><span className="kpi-s">{s.people} people · {s.places} places · {s.things} things</span></div>
        <div className="kpi"><span className="kpi-l">Confidence</span><b>{s.avgConfidence === null ? "—" : `${Math.round(s.avgConfidence * 100)}%`}</b><span className="kpi-s">average across current facts</span></div>
        <div className={`kpi ${kept === 0 ? "good" : "bad"}`}><span className="kpi-l">Raw media kept</span><b>{formatBytes(kept)}</b><span className="kpi-s">{kept === 0 ? "photos and audio are discarded" : "check the privacy settings"}</span></div>
      </section>

      <div className="dash-grid">
        <section className="card pad dash-card span-2" aria-labelledby="d-next">
          <h3 id="d-next">Suggested next steps</h3>
          {suggestions.length === 0 && <p className="muted small">You have tried everything on the demo path. Reset to run it again.</p>}
          <ul className="steps-list">
            {suggestions.map((x) => (
              <li key={x.title}>
                <div><strong>{x.title}</strong><span className="muted small">{x.text}</span></div>
                <button type="button" className={`btn small ${x.primary ? "primary" : ""}`} disabled={p.busy || p.offline} onClick={x.run}>{x.action}</button>
              </li>
            ))}
          </ul>
        </section>

        <section className="card pad dash-card" aria-labelledby="d-ev">
          <h3 id="d-ev">How facts are known</h3>
          <div className="donut-row">
            <Donut parts={[
              { label: "Observed", value: s.evidence.observed, color: "var(--accent)" },
              { label: "Confirmed", value: s.evidence.confirmed, color: "var(--ok)" },
              { label: "Inferred", value: s.evidence.inferred, color: "var(--warn)" },
            ]} />
            <ul className="key">
              <li><i style={{ background: "var(--accent)" }} />Observed <b>{s.evidence.observed}</b></li>
              <li><i style={{ background: "var(--ok)" }} />Confirmed by you <b>{s.evidence.confirmed}</b></li>
              <li><i style={{ background: "var(--warn)" }} />Inferred <b>{s.evidence.inferred}</b></li>
            </ul>
          </div>
        </section>

        <section className="card pad dash-card" aria-labelledby="d-src">
          <h3 id="d-src">Where facts come from</h3>
          {s.sources.length ? <Bars rows={s.sources} colorOf={(l) => SOURCE_COLOR[l] ?? "var(--accent)"} /> : <p className="muted small">Nothing yet.</p>}
        </section>

        <section className="card pad dash-card" aria-labelledby="d-cat">
          <h3 id="d-cat">What the memory is about</h3>
          {s.categories.length ? <Bars rows={s.categories.map((c) => ({ label: CATEGORY_INFO[c.category].title, count: c.count }))} /> : <p className="muted small">Nothing yet.</p>}
        </section>

        <section className="card pad dash-card" aria-labelledby="d-priv">
          <h3 id="d-priv">Consent and privacy</h3>
          <ul className="privacy">
            <li className={kept === 0 ? "ok" : "bad"}>{kept === 0 ? "✓" : "!"} Raw media retained: {formatBytes(kept)}</li>
            <li className="ok">✓ Code, not the model, decides what is stored and deleted</li>
            <li className={p.health?.llm_mode === "live" ? "" : "warn"}>{p.health?.llm_mode === "live" ? "●" : "◐"} Model: {p.health?.llm_mode === "live" ? "live (Muse Spark)" : p.health?.llm_mode === "record" ? "recording" : "replaying recorded responses"}</li>
          </ul>
          {p.grants.length > 0 && (
            <ul className="grants-mini">
              {p.grants.map((g) => (
                <li key={g.grant_id}>
                  <span><strong>{personName(g.grantor)}</strong> <span className="muted small">{sessionLabel(g.scope_ref)}</span></span>
                  {g.revoked_at ? <span className="chip bad">Withdrawn</span> : <span className="chip ok">Active</span>}
                </li>
              ))}
            </ul>
          )}
          <div className="row-actions">
            <button type="button" className="btn small" onClick={p.onConsent}>Manage consent</button>
            {receipt && lastReceiptId && <button type="button" className="btn small" onClick={() => p.onReceipt(lastReceiptId)}>View receipt</button>}
          </div>
        </section>

        {receipt && (
          <section className="card pad dash-card" aria-labelledby="d-rcpt">
            <h3 id="d-rcpt">Latest forgetting</h3>
            <div className="mini-stats">
              <div><b>{receipt.removed.claims_deleted}</b><span>facts removed</span></div>
              <div><b>{receipt.kept.claims_surviving}</b><span>kept, still supported</span></div>
              <div className={receipt.summary.all_passed ? "good" : "bad"}><b>{receipt.summary.probes_passed}/{receipt.summary.probes_total}</b><span>leak checks passed{receipt.summary.probes_skipped ? `, ${receipt.summary.probes_skipped} skipped` : ""}</span></div>
            </div>
          </section>
        )}

        <section className="card pad dash-card span-2" aria-labelledby="d-day">
          <div className="card-head">
            <h3 id="d-day">The day so far</h3>
            <span className="muted small">{played} of {total} events played</span>
          </div>
          <progress value={played} max={Math.max(total, 1)} aria-label="Events played" />
          {cards.length === 0 ? <p className="muted small">No moments yet.</p> : (
            <ul className="mini-moments">
              {cards.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => p.onOpenMoment(c.id)}>
                    <time>{c.time}</time>
                    <span><strong>{c.title}</strong><span className="muted small">{c.facts} facts · {[...c.people, ...c.places, ...c.things].slice(0, 4).map((n) => n.name).join(", ")}</span></span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api, ApiError } from "./api/client";
import { AnnouncerProvider, useAnnounce } from "./hooks/announce";
import { useAtlas } from "./hooks/useAtlas";
import {
  atTime, buildElements, claimIdOfFact, dayCards, describeGraph, episodeOptions, moments as momentsOf,
  pathElementIds, relatedFactClaims, type FactMode, type Selection, type ViewMode,
} from "./utils/graph";
import { readPalette, watchColorScheme, type Palette } from "./utils/theme";
import { AskPanel, type QA } from "./components/AskPanel";
import { ConsentDevice } from "./components/ConsentDevice";
import { ConsentPanel } from "./components/ConsentPanel";
import { AddMemory } from "./components/AddMemory";
import { Dialog } from "./components/Dialog";
import { EvidenceDrawer } from "./components/Evidence";
import { DayOverview } from "./components/DayOverview";
import { FactsPanel } from "./components/FactsPanel";
import { GraphView, type GraphHandle } from "./components/GraphView";
import { Header, type Page } from "./components/Header";
import { Dashboard } from "./components/Dashboard";
import { useTheme } from "./hooks/useTheme";
import { HowItWorks } from "./components/HowItWorks";
import { Welcome } from "./components/Welcome";
import { Legend } from "./components/Legend";
import { ReceiptDialog } from "./components/ReceiptDialog";
import { SelectionCard } from "./components/SelectionCard";
import { Timeline } from "./components/Timeline";

export function App() {
  const params = new URLSearchParams(window.location.search);
  // The simulated phone of the person withdrawing consent, opened in a second tab.
  if (params.get("as") === "device" && params.get("grant")) {
    return (
      <main className="standalone">
        <h1 className="sr-only">MemoryAtlas: consent on the other person's device (simulated)</h1>
        <ConsentDevice grantId={params.get("grant")!} onRevoke={(id, token) => api.revoke(id, token)} />
        <p className="small muted" style={{ textAlign: "center" }}>
          This is a simulation. The MemoryAtlas tab you came from will show the forgetting receipt.
        </p>
      </main>
    );
  }
  return (
    <AnnouncerProvider>
      <Atlas />
    </AnnouncerProvider>
  );
}

type Tab = "ask" | "facts" | "consent";
const TABS: { id: Tab; label: string }[] = [{ id: "ask", label: "Ask" }, { id: "facts", label: "Facts" }, { id: "consent", label: "Consent" }];

function Atlas() {
  const atlas = useAtlas();
  const announce = useAnnounce();
  const graphRef = useRef<GraphHandle>(null);

  const [palette, setPalette] = useState<Palette | null>(null);
  const [mode, setMode] = useState<ViewMode>("episodes");
  const [factChoice, setFactChoice] = useState<"off" | "related" | "all">("related");
  const [showHistory, setShowHistory] = useState(true);
  const [episode, setEpisode] = useState<string | null>(null);
  const [scrubAt, setScrubAt] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [selection, setSelection] = useState<Selection>(null);
  const [focus, setFocus] = useState<string[] | null>(null);
  const [evidence, setEvidence] = useState<string[] | null>(null);
  const [tab, setTab] = useState<Tab>("ask");
  const [qas, setQas] = useState<QA[]>([]);
  const [asking, setAsking] = useState(false);
  const [simulate, setSimulate] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  const [adding, setAdding] = useState(false);
  const [page, setPage] = useState<Page>("dashboard");
  const theme = useTheme();
  const qaId = useRef(0);

  // Theme: the canvas needs real colour strings, so re-read them when the system theme flips.
  useEffect(() => {
    setPalette(readPalette());
    return watchColorScheme(() => setPalette(readPalette()));
  }, [theme.tick]);

  // --- what is on screen ----------------------------------------------------------------------
  const moments = useMemo(() => momentsOf(atlas.graph), [atlas.graph]);
  const momentsRef = useRef(moments);
  momentsRef.current = moments;
  const index = useMemo(() => {
    if (scrubAt === null || moments.length === 0) return null;
    const i = moments.reduce((acc, m, k) => (m <= scrubAt ? k : acc), 0);
    return i >= moments.length - 1 ? null : i;
  }, [scrubAt, moments]);

  const view = useMemo(() => atTime(atlas.graph, scrubAt), [atlas.graph, scrubAt]);
  const focusIds = focus ?? (selection?.kind === "claim" ? [selection.id] : null);
  const factMode: FactMode = useMemo(
    () => factChoice === "all" ? "all" : factChoice === "off" ? "none"
      : relatedFactClaims(view, focusIds, selection?.kind === "entity" ? selection.id : null),
    [factChoice, view, focusIds, selection]);
  const elements = useMemo(
    () => buildElements(view, { mode, showFacts: factMode, showHistory, episode }),
    [view, mode, factMode, showHistory, episode]);
  const highlight = useMemo(() => {
    const ids = focus ?? (selection?.kind === "claim" ? [selection.id] : null);
    return ids ? pathElementIds(view, ids) : null;
  }, [focus, selection, view]);
  const selectedId = selection ? selection.id : null;
  const episodes = useMemo(() => episodeOptions(atlas.graph), [atlas.graph]);
  const cards = useMemo(() => dayCards(view), [view]);
  const forgotten = atlas.grants.some((g) => g.revoked_at);

  // --- timeline playback ----------------------------------------------------------------------
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setScrubAt((cur) => {
        const m = momentsRef.current;
        const i = cur === null ? -1 : m.indexOf(cur);
        const next = i + 1;
        if (next >= m.length - 1) { setPlaying(false); return null; }
        return m[next];
      });
    }, 1100);
    return () => window.clearInterval(id);
  }, [playing]);

  const togglePlay = () => {
    if (playing) return setPlaying(false);
    setScrubAt(momentsRef.current[0] ?? null);
    setPlaying(true);
  };
  const jumpTo = (hhmm: string) => {
    const last = [...moments].reverse().find((m) => m.includes(`T${hhmm}`));
    if (last) { setPlaying(false); setScrubAt(last === moments[moments.length - 1] ? null : last); }
  };

  // --- keep the screen honest when the data changes --------------------------------------------
  const firstLoad = useRef(true);
  const pendingNote = useRef<string | null>(null);
  useEffect(() => {
    if (!atlas.loaded) return;
    if (firstLoad.current) { firstLoad.current = false; return; }
    // One live region: a message waiting for this refresh is folded in, or the refresh would replace it.
    const note = pendingNote.current;
    pendingNote.current = null;
    announce(note ? `${note} ${describeGraph(atlas.graph)}` : describeGraph(atlas.graph));
    // a selection or focus on something that no longer exists is dropped
    const ids = new Set(atlas.graph.edges.map((e) => e.id));
    setSelection((s) => (s?.kind === "claim" && !ids.has(s.id) ? null : s));
    setFocus((f) => (f && f.every((id) => !ids.has(id)) ? null : f));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [atlas.dataKey]);

  useEffect(() => {
    if (!atlas.receipt) return;
    announce(`${atlas.receipt.reason === "expired" ? "Consent expired." : "Consent withdrawn."} ${atlas.receipt.removed.claims_deleted} facts removed, ${atlas.receipt.kept.claims_surviving} kept. ` +
      `${atlas.receipt.summary.probes_passed} of ${atlas.receipt.summary.probes_total} checks passed.`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [atlas.receipt]);

  // Jump to the present when facts are removed, so the removal is what you see.
  useEffect(() => {
    if (atlas.pulse.size) { setScrubAt(null); setPlaying(false); setEvidence(null); setFocus(null); }
  }, [atlas.pulse]);

  // --- actions ----------------------------------------------------------------------------------
  const ask = useCallback(async (question: string) => {
    const id = ++qaId.current;
    setTab("ask");
    setAsking(true);
    try {
      const a = await api.ask(question);
      setQas((q) => [{ id, question, answer: a }, ...q]);
      setSelection(null);
      setScrubAt(null);
      setFocus(a.cited_claim_ids.length ? a.cited_claim_ids : null);
      if (a.cited_claim_ids.length) setMode("entities");
      announce(`${a.status === "abstained" ? "No record." : "Answer."} ${a.answer}`);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      setQas((q) => [{ id, question, error: { text: e instanceof Error ? e.message : String(e), notRecorded: !!err?.isNotRecorded } }, ...q]);
    } finally {
      setAsking(false);
    }
  }, [announce]);

  const cite = (claimId: string) => {
    setMode("entities");
    setScrubAt(null);
    setSelection({ kind: "claim", id: claimId });
    setFocus([claimId]);
  };
  const correct = async (claimId: string, body: { text?: string; retract?: boolean; at?: string }) => {
    pendingNote.current = body.retract ? "That fact is set aside and kept as history."
      : "Correction recorded. The earlier fact is kept as history.";
    const ok = await atlas.correct(claimId, body);
    if (!ok) pendingNote.current = null;
    return ok;
  };
  const why = (ids: string[]) => { setEvidence(ids); setFocus(ids); };
  const onSelect = (s: Selection) => {
    // a fact node stands for its claim
    const claim = s?.kind === "entity" ? claimIdOfFact(s.id) : null;
    setSelection(claim ? { kind: "claim", id: claim } : s);
    setFocus(null);
  };
  const openEpisode = (id: string) => { setMode("entities"); setEpisode(id); setSelection(null); };

  const reset = async () => {
    await atlas.reset();
    setQas([]); setSelection(null); setFocus(null); setEvidence(null); setScrubAt(null);
    setPlaying(false); setEpisode(null);
  };

  const openReceipt = async (id: string) => {
    try { atlas.openReceipt(await api.receipt(id)); }
    catch (e) { atlas.setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) }); }
  };

  return (
    <div className="app">
      <a className="skip-link" href="#main">Skip to the main content</a>
      <Header
        health={atlas.health} media={atlas.media} status={atlas.status} busy={atlas.busy} offline={atlas.offline}
        onNext={() => void atlas.advance(1)} onAll={() => void atlas.advance(50)}
        onLive={(id) => void atlas.uploadLive(id)} onReset={() => void reset()} onHelp={() => setHelp(true)} onAdd={() => setAdding(true)}
        page={page} onPage={setPage} theme={theme.pref} onTheme={theme.choose}
      />

      {page === "dashboard" ? (
        <main className="dash-wrap" id="main">
          <Dashboard
            graph={atlas.graph} status={atlas.status} media={atlas.media} health={atlas.health} grants={atlas.grants}
            busy={atlas.busy !== null} offline={atlas.offline}
            onPlayNext={() => void atlas.advance(1)} onPlayAll={() => void atlas.advance(50)}
            onOpenAtlas={() => setPage("atlas")}
            onOpenMoment={(id) => { setPage("atlas"); openEpisode(id); }}
            onAsk={(q) => { setPage("atlas"); void ask(q); }}
            onConsent={() => { setPage("atlas"); setTab("consent"); }}
            onReceipt={(id) => void openReceipt(id)}
            onLive={(id) => void atlas.uploadLive(id)} onReset={() => void reset()}
          />
        </main>
      ) : (
      <div className="layout">
        <main className="stage" id="main">
          {atlas.notice && (
            <div className={`notice ${atlas.notice.kind}`} role={atlas.notice.kind === "error" ? "alert" : "status"}>
              <span>{atlas.notice.text}</span>
              <button type="button" className="btn small ghost" onClick={() => atlas.setNotice(null)}>Dismiss</button>
            </div>
          )}

          <div className="toolbar" role="toolbar" aria-label="Graph view">
            <div className="seg" role="group" aria-label="View">
              <button type="button" aria-pressed={mode === "episodes"} onClick={() => { setMode("episodes"); setEpisode(null); }}>Day</button>
              <button type="button" aria-pressed={mode === "entities"} onClick={() => setMode("entities")}>Map</button>
            </div>
            {mode === "entities" && (
              <>
                <label className="sr-only" htmlFor="episode">Show one moment</label>
                <select id="episode" value={episode ?? ""} onChange={(e) => setEpisode(e.target.value || null)}>
                  <option value="">All moments</option>
                  {episodes.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
                </select>
                <label className="sr-only" htmlFor="facts">Facts shown as boxes</label>
                <select id="facts" value={factChoice} onChange={(e) => setFactChoice(e.target.value as typeof factChoice)}
                        title="Details are small facts such as what was said or a colour">
                  <option value="related">Details: for what I select</option>
                  <option value="all">Details: show all</option>
                  <option value="off">Details: hide</option>
                </select>
              </>
            )}
            {mode === "entities" && <label className="check" title="Show facts that newer evidence replaced"><input type="checkbox" checked={showHistory} onChange={(e) => setShowHistory(e.target.checked)} /> Show history</label>}
            <span className="spacer" />
            {(focus || selection) && (
              <button type="button" className="btn small" onClick={() => { setFocus(null); setSelection(null); }}>Clear focus</button>
            )}
            {mode === "entities" && <div className="seg" role="group" aria-label="Zoom">
              <button type="button" aria-label="Zoom out" onClick={() => graphRef.current?.zoomOut()}>−</button>
              <button type="button" onClick={() => graphRef.current?.fit()}>Fit</button>
              <button type="button" aria-label="Zoom in" onClick={() => graphRef.current?.zoomIn()}>+</button>
            </div>}
          </div>

          <figure className={`graph-figure ${mode === "episodes" ? "is-day" : ""}`}>
            <div className="graph-stage">
            {mode === "entities" && palette && (
              <GraphView
                ref={graphRef} elements={elements} palette={palette} highlight={highlight} selectedId={selectedId}
                pulse={atlas.pulse} dataKey={atlas.dataKey} viewKey={`${mode}|${episode}`}
                layoutKind="timeline" label={describeGraph(view)} onSelect={onSelect}
              />
            )}
            {mode === "entities" && elements.length > 0 && !selection && (
              <p className="graph-hint">Hover to trace connections · click anything for details · drag to move around</p>
            )}
            {mode === "entities" && selection && (
              <SelectionCard full={atlas.graph} view={view} selection={selection}
                             onSelect={(s) => { setSelection(s); setFocus(null); }} onWhy={why}
                             onCorrect={correct} replay={atlas.health?.llm_mode === "replay"}
                             onOpenEpisode={openEpisode} onClose={() => { setSelection(null); setFocus(null); }} />
            )}
            </div>
            {mode === "episodes" && cards.length > 0 && (
              <DayOverview cards={cards} selectedId={selection?.kind === "episode" ? selection.id : null}
                           onSelect={(id) => setSelection({ kind: "episode", id })} onOpenInMap={openEpisode} />
            )}
            {atlas.loaded && view.edges.length === 0 && scrubAt === null && (
              <Welcome disabled={atlas.busy !== null} offline={atlas.offline}
                       onPlayDay={() => void atlas.advance(50)} onStep={() => void atlas.advance(1)} />
            )}
            {atlas.loaded && view.edges.length === 0 && scrubAt !== null && (
              <div className="graph-empty">
                <strong>Nothing had happened yet</strong>
                <span>Move the timeline forward.</span>
              </div>
            )}
            <figcaption className="sr-only">{describeGraph(view)} The Facts tab lists the same facts as text.</figcaption>
            {mode === "entities" && <Legend />}
          </figure>

          <Timeline
            moments={moments} index={index} events={atlas.status?.events ?? []} playing={playing}
            onIndex={(i) => { setPlaying(false); setScrubAt(i === null ? null : moments[i]); }}
            onTogglePlay={togglePlay} onJump={jumpTo}
          />
        </main>

        <aside className="side" aria-label="Ask and consent">
          <TabBar tab={tab} onTab={setTab} />
          <div role="tabpanel" id="panel-ask" aria-labelledby="tab-ask" hidden={tab !== "ask"} tabIndex={0}>
            <AskPanel qas={qas} asking={asking} forgotten={forgotten} mode={atlas.health?.llm_mode}
                      onAsk={(q) => void ask(q)} onCite={cite} onWhy={why} />
          </div>
          <div role="tabpanel" id="panel-facts" aria-labelledby="tab-facts" hidden={tab !== "facts"} tabIndex={0}>
            <FactsPanel view={view} selectedClaim={selection?.kind === "claim" ? selection.id : null} onSelect={cite} />
          </div>
          <div role="tabpanel" id="panel-consent" aria-labelledby="tab-consent" hidden={tab !== "consent"} tabIndex={0}>
            <ConsentPanel grants={atlas.grants} onSimulate={setSimulate} onExpire={(id) => void atlas.expire(id)} onReceipt={(id) => void openReceipt(id)} />
          </div>
        </aside>
      </div>
      )}

      <AddMemory open={adding} mode={atlas.health?.llm_mode} onClose={() => setAdding(false)} onSaved={() => void atlas.refresh()} />
      <HowItWorks open={help} onClose={() => setHelp(false)} />
      <EvidenceDrawer claimIds={evidence} onClose={() => setEvidence(null)} />
      <ReceiptDialog receipt={atlas.receipt} onClose={atlas.closeReceipt} />
      <Dialog open={simulate !== null} onClose={() => setSimulate(null)} title="Simulated device" initialFocus="[data-autofocus]">
        {simulate && (
          <ConsentDevice
            grantId={simulate} onRevoke={atlas.revoke}
            onDone={() => window.setTimeout(() => setSimulate(null), 900)}
          />
        )}
        <p className="small muted">In a real deployment this happens on the other person's own device. Here the demo plays both sides.</p>
      </Dialog>
    </div>
  );
}

/** Tabs with the keyboard behaviour the ARIA pattern promises: arrows move, only one tab is tabbable. */
function TabBar({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const onKey = (e: KeyboardEvent) => {
    const i = TABS.findIndex((t) => t.id === tab);
    const next = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i + TABS.length - 1) % TABS.length
      : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    onTab(TABS[next].id);
    refs.current[TABS[next].id]?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label="Side panel" onKeyDown={onKey}>
      {TABS.map((t) => (
        <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`} tabIndex={tab === t.id ? 0 : -1}
                ref={(el) => { refs.current[t.id] = el; }} onClick={() => onTab(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

import type { DemoStatus, Health, Media } from "../api/types";
import { formatBytes, truncate } from "../utils/graph";
import type { ThemePref } from "../hooks/useTheme";
import { ThemeToggle } from "./ThemeToggle";

export type Page = "dashboard" | "atlas";

type Props = {
  health: Health | null;
  media: Media | null;
  status: DemoStatus | null;
  busy: string | null;
  offline: boolean;
  onNext: () => void;
  onAll: () => void;
  onLive: (id: string) => void;
  onReset: () => void;
  onHelp: () => void;
  page: Page;
  onPage: (p: Page) => void;
  theme: ThemePref;
  onTheme: (t: ThemePref) => void;
};

const MODE: Record<string, { text: string; cls: string; hint: string }> = {
  replay: { text: "Replay mode", cls: "warn", hint: "Answers come from recorded model responses, not a live model call." },
  live: { text: "Live · Muse Spark", cls: "ok", hint: "Every answer is a live call to the Meta Model API." },
  record: { text: "Recording", cls: "accent", hint: "Live calls, saved so they can be replayed later." },
};

export function Header({ health, media, status, busy, offline, onNext, onAll, onLive, onReset, onHelp, page, onPage, theme, onTheme }: Props) {
  const mode = health ? MODE[health.llm_mode] : undefined;
  const nextEvent = status?.events.find((e) => e.id === status.next);
  const live = status?.events.filter((e) => e.live_upload && !e.played) ?? [];
  const kept = media?.raw_media_bytes_retained ?? 0;
  const disabled = busy !== null || offline;

  return (
    <header className="header">
      <div className="brand">
        <span className="logo" aria-hidden="true" />
        <h1>MemoryAtlas</h1>
        <span className="tagline">memories with receipts</span>
      </div>

      <nav className="seg page-nav" aria-label="Main">
        <button type="button" aria-pressed={page === "dashboard"} onClick={() => onPage("dashboard")}>Dashboard</button>
        <button type="button" aria-pressed={page === "atlas"} onClick={() => onPage("atlas")}>Atlas</button>
      </nav>

      <div className="group" aria-label="Status">
        {offline && <span className="chip bad">Backend unreachable</span>}
        {mode && <span className={`chip ${mode.cls}`} title={mode.hint}>{mode.text}</span>}
        {media && (
          <span className={`chip ${kept === 0 ? "ok" : "bad"}`}
                title="Photos and audio are turned into text and discarded. This counts what the database retains.">
            {kept === 0 ? "✓ " : ""}Raw media kept: {formatBytes(kept)}
          </span>
        )}
      </div>

      {page === "atlas" && (
      <div className="group" role="group" aria-label="Demo day controls">
        {busy && <progress aria-label={busy} />}
        <button type="button" className="btn primary" disabled={disabled || !nextEvent} onClick={onNext}>
          {nextEvent ? `Play next: ${nextEvent.at} ${truncate(kindWord(nextEvent.kind, nextEvent.label), 24)}` : "Day played"}
        </button>
        <button type="button" className="btn" disabled={disabled || !nextEvent} onClick={onAll}>Play the day</button>
        {live.map((e) => (
          <button type="button" className="btn" key={e.id} disabled={disabled} onClick={() => onLive(e.id)}
                  title={e.label}>
            Upload live photo · {e.at}
          </button>
        ))}
        <button type="button" className="btn ghost" disabled={disabled} onClick={onReset}>Reset</button>
      </div>
      )}

      <div className="group">
        <button type="button" className="btn ghost" onClick={onHelp} aria-haspopup="dialog">How it works</button>
        <ThemeToggle pref={theme} onChange={onTheme} />
      </div>
    </header>
  );
}

export function kindWord(kind: string, label: string): string {
  if (kind === "calendar") return label;
  if (kind === "audio") return "conversation";
  return kind === "frame" ? "photo" : label;
}

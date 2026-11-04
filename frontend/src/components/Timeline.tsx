import type { DemoEvent } from "../api/types";
import { clock, truncate } from "../utils/graph";
import { kindWord } from "./DemoTools";

type Props = {
  moments: string[];
  /** Index into `moments`, or null for "now". */
  index: number | null;
  events: DemoEvent[];
  playing: boolean;
  onIndex: (i: number | null) => void;
  onTogglePlay: () => void;
  onJump: (hhmm: string) => void;
};

export function Timeline({ moments, index, events, playing, onIndex, onTogglePlay, onJump }: Props) {
  const last = moments.length - 1;
  const value = index ?? Math.max(last, 0);
  const current = moments[value] ? clock(moments[value]) : "";
  const text = moments.length === 0 ? "Nothing yet" : index === null ? `Now · ${current}` : current;
  const pct = last > 0 ? (value / last) * 100 : 100;
  const here = events.find((e) => e.played && e.at === current);

  return (
    <section className="card pad timeline" aria-label="Day timeline">
      <div className="timeline-row">
        <button type="button" className="btn small" aria-pressed={playing} disabled={moments.length < 2} onClick={onTogglePlay}>
          {playing ? "Pause" : "Watch it build"}
        </button>
        <div>
          <label htmlFor="scrub">Scrub through the day</label>
          <input
            id="scrub" type="range" min={0} max={Math.max(last, 0)} step={1} value={value}
            disabled={moments.length < 2}
            style={{ ["--pos" as string]: `${pct}%` }}
            aria-valuetext={`${text}${here ? `, ${kindWord(here.kind, here.label)}` : ""}`}
            onChange={(e) => { const i = Number(e.target.value); onIndex(i >= last ? null : i); }}
          />
        </div>
        <output htmlFor="scrub">{text}</output>
      </div>
      <ol className="events" aria-label="Events of the day">
        {events.map((e) => (
          <li key={e.id}>
            <button
              type="button" className={`event ${e.played ? "" : "future"} ${e.live_upload ? "live" : ""}`}
              disabled={!e.played} aria-current={e.played && e.at === current ? "true" : undefined}
              onClick={() => onJump(e.at)}
              title={e.played ? e.label : `${e.label} (not played yet)`}
            >
              <span className="t">{e.at}</span>
              <span>{truncate(kindWord(e.kind, e.label), 28)}</span>
              {e.live_upload && <span className="chip warn">live</span>}
              {!e.played && <span className="sr-only">not played yet</span>}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

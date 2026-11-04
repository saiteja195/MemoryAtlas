import type { Coverage } from "../api/types";
import { formatMinutes, gapBox, hourLabel, stripBlocks } from "../utils/insights";

const TICKS = [6, 9, 12, 15, 18, 21];

/** The waking day (06:00 to 22:00) as one bar: filled where memories exist, dashed over the longest silence. */
export function CoverageStrip({ coverage }: { coverage: Coverage | null }) {
  const empty = !coverage || (coverage.spans.length === 0 && coverage.covered_hours === 0);
  if (!coverage || empty) {
    return <p className="muted cov-empty">Add a memory to see your day</p>;
  }
  const [first, last] = coverage.window;
  const blocks = stripBlocks(coverage);
  const gap = gapBox(coverage);
  const pct = Math.round(Math.min(1, Math.max(0, coverage.share)) * 100);
  const at = (h: number) => ((h - first) / Math.max(1, last - first)) * 100;
  const summary = `${pct}% of waking hours covered, busiest hour ${hourLabel(coverage.busiest_hour)}`
    + (gap ? `, ${gap.label}` : "");
  return (
    <div className="cov">
      <div className="cov-scroll">
        <div className="cov-inner">
          <div className="cov-label-row" aria-hidden="true">
            {gap && (
              <span className={`cov-gap-label${gap.left > 50 ? " end" : ""}`}
                    style={gap.left > 50 ? { insetInlineEnd: `${Math.max(0, 100 - gap.left - gap.width)}%` }
                                         : { insetInlineStart: `${gap.left}%` }}>
                {gap.label}
              </span>
            )}
          </div>
          <div className="cov-track" role="img" aria-label={summary}>
            {blocks.map((b, i) => (
              <span key={i} className="cov-block" style={{ insetInlineStart: `${b.left}%`, inlineSize: `${b.width}%` }} />
            ))}
            {gap && <span className="cov-gap" style={{ insetInlineStart: `${gap.left}%`, inlineSize: `${gap.width}%` }} />}
          </div>
          <div className="cov-ticks" aria-hidden="true">
            {TICKS.filter((h) => h >= first && h < last).map((h) => (
              <span key={h} style={{ insetInlineStart: `${at(h)}%` }}>{h}</span>
            ))}
          </div>
        </div>
      </div>
      <dl className="cov-figs">
        <div><dd>{pct}%</dd><dt>of waking hours</dt></div>
        <div><dd>{hourLabel(coverage.busiest_hour)}</dd><dt>busiest hour</dt></div>
        <div><dd>{coverage.longest_gap ? formatMinutes(coverage.longest_gap.minutes) : "none"}</dd><dt>longest gap</dt></div>
      </dl>
    </div>
  );
}

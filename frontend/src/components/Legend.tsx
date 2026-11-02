const line = (stroke: string, dash?: string, w = 3, extra?: React.CSSProperties) => (
  <svg className="swatch" viewBox="0 0 34 10" aria-hidden="true">
    <line x1="2" y1="5" x2="32" y2="5" strokeWidth={w} strokeDasharray={dash} strokeLinecap="round"
          style={{ stroke, ...extra }} />
  </svg>
);

/** What the picture means. Colour is never the only signal: shape, dashes and a clock back it up. */
export function Legend() {
  return (
    <div className="legend">
      <ul className="legend-quick" aria-label="What the symbols mean">
        <li><span className="dot-i" style={{ background: "var(--c-person)" }}>👤</span> Person</li>
        <li><span className="dot-i sq" style={{ background: "var(--c-place)" }}>📍</span> Place</li>
        <li><span className="dot-i dia" style={{ background: "var(--c-object)" }}><i>◆</i></span> Thing</li>
        <li>{line("var(--s-none)")} Seen directly</li>
        <li>{line("var(--s-derivation)", "7 4")} Worked out</li>
        <li>{line("var(--muted)", "2 4", 3)} Replaced</li>
      </ul>
    <details className="legend-more">
      <summary>All symbols</summary>
      <ul className="legend-body">
        <li>{line("var(--s-none)")} Observed directly</li>
        <li>{line("var(--s-derivation)", "7 4")} Inferred from other facts</li>
        <li>{line("var(--s-none)", undefined, 3, { filter: "drop-shadow(0 0 3px var(--ok))" })} Confirmed by you</li>
        <li>{line("var(--muted)", "2 4", 3)} ⏱ Replaced by newer evidence</li>
        <li>{line("var(--s-multi)", undefined, 5)} Supported by several sources (×N)</li>
        <li>{line("var(--s-frame_observation)")} From a photo</li>
        <li>{line("var(--s-transcript_segment)")} From the conversation</li>
        <li>{line("var(--s-calendar_event)")} From the calendar</li>
        <li><span className="shape circle" style={{ color: "var(--c-person)" }} /> Person</li>
        <li><span className="shape box" style={{ color: "var(--c-place)" }} /> Place</li>
        <li><span className="shape diamond" style={{ color: "var(--c-object)" }} /> Thing</li>
        <li><span className="shape box" style={{ color: "var(--c-fact)", blockSize: 10 }} /> A fact about something</li>
      </ul>
    </details>
    </div>
  );
}

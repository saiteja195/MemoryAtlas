import { TypeIcon } from "./TypeIcon";

/** The same tinted icon square the Atlas cards use. */
const chip = (type: string, colour: string) => (
  <span className="type-chip" style={{ color: colour }} aria-hidden="true"><TypeIcon type={type} /></span>
);

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
        <li>{chip("person", "var(--c-person)")} Person</li>
        <li>{chip("place", "var(--c-place)")} Place</li>
        <li>{chip("object", "var(--c-object)")} Thing</li>
        <li>{line("var(--s-none)")} Seen directly</li>
        <li>{line("var(--s-derivation)", "7 4")} Worked out</li>
        <li>{line("var(--muted)", "2 4", 3)} Replaced</li>
      </ul>
    <details className="legend-more">
      <summary>All symbols</summary>
      <ul className="legend-body">
        <li>{line("var(--s-none)")} Seen directly</li>
        <li>{line("var(--s-derivation)", "7 4")} Inferred from other facts</li>
        <li>{line("var(--s-none)", undefined, 3, { filter: "drop-shadow(0 0 3px var(--ok))" })} Confirmed by you</li>
        <li>{line("var(--muted)", "2 4", 3)} ⏱ Replaced by newer evidence</li>
        <li>{line("var(--s-multi)", undefined, 5)} Supported by several sources (×N)</li>
        <li>{chip("person", "var(--c-person)")} Person</li>
        <li>{chip("place", "var(--c-place)")} Place</li>
        <li>{chip("object", "var(--c-object)")} Thing</li>
        <li>{chip("org", "var(--c-org)")} Organisation</li>
        <li><span className="shape box" style={{ color: "var(--border)", blockSize: 10 }} /> A detail about something</li>
      </ul>
    </details>
    </div>
  );
}

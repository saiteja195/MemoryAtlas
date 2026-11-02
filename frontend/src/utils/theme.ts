// Bridges CSS design tokens to the places that need plain colour strings (the graph canvas).
//
// Custom properties defined with light-dark() are NOT resolved when read back with
// getPropertyValue (you get the literal "light-dark(...)" text). The reliable way is to apply the
// token to a real property on a real element and read the computed value.

export const TOKENS = [
  "bg", "surface", "surface-2", "text", "muted", "border", "accent", "ok", "warn", "bad",
  "c-person", "c-place", "c-object", "c-org", "c-item", "c-fact", "c-episode",
  "s-frame_observation", "s-transcript_segment", "s-calendar_event", "s-user_confirmation",
  "s-derivation", "s-multi", "s-none",
] as const;

export type Palette = Record<(typeof TOKENS)[number], string>;

export function readPalette(): Palette {
  const probe = document.createElement("span");
  probe.setAttribute("aria-hidden", "true");
  probe.style.cssText = "position:absolute;visibility:hidden;pointer-events:none;inline-size:0;block-size:0";
  document.body.appendChild(probe);
  const out = {} as Palette;
  for (const t of TOKENS) {
    probe.style.color = `var(--${t})`;
    out[t] = getComputedStyle(probe).color;
  }
  probe.remove();
  return out;
}

/** Calls back whenever the system colour scheme changes. Returns an unsubscribe function. */
export function watchColorScheme(onChange: () => void): () => void {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

export const prefersReducedMotion = (): boolean =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

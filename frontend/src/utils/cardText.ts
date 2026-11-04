// How a name becomes a card on the Atlas: cleaned, given a stand-in when empty, cut to fit with an
// ellipsis, and a card width that always leaves padding between the text and the border.
// Pure functions: the one thing that needs a browser (measuring text) is passed in, so tests need no canvas.

export const CARD = {
  h: 40,
  minW: 96,
  maxW: 224,
  chip: 28,      // the tinted icon square on the left
  pad: 12,       // between the text (and the chip) and the card's border
  gap: 8,        // between the chip and the text
  fontPx: 13,
  font: "600 13px system-ui, -apple-system, sans-serif", // must match the Cytoscape label style
} as const;

export type Measure = (text: string) => number;

/** Room for text inside a card of the given width. */
export const textRoom = (cardW: number): number => cardW - 2 * CARD.pad - CARD.chip - CARD.gap;

let ctx: CanvasRenderingContext2D | null | undefined;
function canvas(): CanvasRenderingContext2D | null {
  if (ctx !== undefined) return ctx;
  try {
    ctx = typeof document === "undefined" ? null : document.createElement("canvas").getContext("2d");
    if (ctx) ctx.font = CARD.font;
  } catch {
    ctx = null;
  }
  return ctx;
}

/** Width in pixels of `text` in the card font. Falls back to an estimate where there is no canvas. */
export const measureCard: Measure = (text) => {
  const c = canvas();
  if (c) return c.measureText(text).width;
  let w = 0;
  for (const ch of text) w += (ch.codePointAt(0) ?? 0) >= 0x2e80 ? CARD.fontPx : CARD.fontPx * 0.58;
  return w;
};

/** One line of plain text: whitespace collapsed, control and zero-width characters dropped. */
export function cleanText(s: unknown): string {
  if (typeof s !== "string" && typeof s !== "number") return "";
  return String(s)
    .replace(/[\r\n\t]+/g, " ")
    .replace(/[\u0000-\u001f\u007f-\u009f​-‏⁠﻿]/g, "")
    .replace(/ {2,}/g, " ")
    .trim();
}

/** What a card says when it has no name. */
export function fallbackName(type: string): string {
  return type === "person" ? "Unnamed person" : type === "place" || type === "org" ? "Unnamed place" : "Unnamed thing";
}

/** `text`, cut with an ellipsis if it is wider than `maxPx`. Cuts whole characters, never half an emoji. */
export function fitText(text: string, maxPx: number, measure: Measure): string {
  if (!text) return "";
  if (measure(text) <= maxPx) return text;
  const chars = Array.from(text);
  const cut = (k: number) => chars.slice(0, k).join("").trimEnd() + "…";
  let lo = 0, hi = chars.length - 1;            // the largest k whose cut still fits; k = 0 is just the ellipsis
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (measure(cut(mid)) <= maxPx) lo = mid; else hi = mid - 1;
  }
  return cut(lo);
}

export type CardLayout = {
  /** What is drawn on the card: cleaned and cut to fit. */
  label: string;
  /** The whole name, for the tooltip and the details. */
  full: string;
  /** Card width in pixels. */
  w: number;
  /** True when the name was missing and `label` is a stand-in. */
  unnamed: boolean;
};

export function cardLayout(name: unknown, type: string, measure: Measure = measureCard): CardLayout {
  const clean = cleanText(name);
  const unnamed = clean === "";
  const full = unnamed ? fallbackName(type) : clean;
  const label = fitText(full, textRoom(CARD.maxW), measure);
  const w = Math.min(CARD.maxW, Math.max(CARD.minW, Math.ceil(2 * CARD.pad + CARD.chip + CARD.gap + measure(label))));
  return { label, full, w, unnamed };
}

// The Cytoscape stylesheet. Meaning is carried by more than colour:
//   how a claim is known   -> line style  (solid observed, dashed amber inferred, haloed confirmed)
//   whether it is current  -> opacity     (replaced claims are faded and dotted, with a clock)
//   what kind of thing     -> icon chip   (person, place, thing... a tinted square with a line icon)
// Lines are quiet grey until you point at, select or trace them; then they take the accent colour and
// show what the relationship is.
import type cytoscape from "cytoscape";
import type { Palette } from "./theme";
import { CARD } from "./cardText";
import { chipImage } from "./icons";

type Rule = { selector: string; style: Record<string, unknown> };

const FAMILY = "system-ui, -apple-system, sans-serif";
const CHIP_INSET = CARD.pad / 2;
/** Cards centre their text in the whole node, so push it right by half the space the chip takes. */
const TEXT_SHIFT = (CHIP_INSET + CARD.chip + CARD.gap - CARD.pad) / 2;

const chip = (type: string, color: string): Record<string, unknown> => ({
  "background-image": chipImage(type, color), "background-fit": "none", "background-clip": "node",
  "background-width": CARD.chip, "background-height": CARD.chip,
  "background-position-x": CHIP_INSET, "background-position-y": "50%", "background-image-containment": "inside",
});

export function buildStylesheet(p: Palette): cytoscape.StylesheetStyle[] {
  const rules: Rule[] = [
    { selector: "node", style: {
      width: 54, height: 54, label: "data(label)", "font-size": 14, "font-weight": 600, color: p.text,
      "font-family": FAMILY, "text-valign": "center", "text-halign": "center",
      "text-wrap": "wrap", "text-max-width": 120, "background-color": p["surface-2"],
      "border-width": 1, "border-color": p.border,
      "text-background-opacity": 0, "transition-property": "opacity, text-opacity, border-color", "transition-duration": 160,
      "min-zoomed-font-size": 6,
    } },

    // People, places and things: a card with an icon chip, the name beside it, padding all round.
    { selector: ".entity", style: {
      shape: "round-rectangle", width: "data(w)", height: CARD.h, "font-size": CARD.fontPx, "font-weight": 600,
      "text-wrap": "ellipsis", "text-max-width": "data(tw)", "text-margin-x": TEXT_SHIFT, "text-margin-y": 0,
      "background-color": p["surface-2"], "border-width": 1, "border-color": p.border,
    } },
    { selector: ".type-person", style: chip("person", p["c-person"]) },
    { selector: ".type-place", style: chip("place", p["c-place"]) },
    { selector: ".type-object", style: chip("object", p["c-object"]) },
    { selector: ".type-org", style: chip("org", p["c-org"]) },
    { selector: ".type-item", style: chip("item", p["c-item"]) },
    { selector: ".owner", style: { "border-color": p.accent, "border-width": 1.5 } },
    { selector: ".unnamed", style: { color: p.muted, "font-style": "italic", "font-weight": 500 } },

    // Details about a card (a literal fact): a small quiet pill.
    { selector: ".fact", style: {
      shape: "round-rectangle", width: "data(w)", height: 24, "font-size": 11, "font-weight": 500, color: p.muted,
      "text-wrap": "none", "background-color": p.surface, "border-width": 1, "border-color": p.border,
    } },
    // A moment: a roomier card that wraps its two lines.
    { selector: ".episode", style: {
      shape: "round-rectangle", width: 190, height: 76, "text-wrap": "wrap", "text-max-width": 166, "font-size": 14,
      "background-color": p["surface-2"], "border-width": 1, "border-color": p.border,
    } },

    // Relationship lines: thin, grey, curved.
    { selector: "edge", style: {
      width: 1.5, "curve-style": "bezier", "line-color": p["s-none"], "target-arrow-color": p["s-none"],
      "target-arrow-shape": "triangle", "arrow-scale": 0.8, label: "", "font-size": 11, "font-weight": 500,
      color: p.text, "text-rotation": "none", "text-wrap": "ellipsis", "text-max-width": 150,
      "text-background-color": p.surface, "text-background-opacity": 1, "text-background-padding": 4,
      "text-background-shape": "roundrectangle", "text-border-width": 1, "text-border-color": p.border, "text-border-opacity": 1,
      "min-zoomed-font-size": 7, "transition-property": "opacity, line-color, width", "transition-duration": 160,
    } },
    { selector: "edge.src-multi", style: { width: 2.6 } },
    { selector: "edge.ev-inferred", style: { "line-style": "dashed", "line-dash-pattern": [7, 5], "line-color": p["s-derivation"], "target-arrow-color": p["s-derivation"] } },
    { selector: "edge.ev-confirmed", style: { "underlay-color": p.ok, "underlay-opacity": 0.3, "underlay-padding": 4 } },
    { selector: "edge.to-fact", style: { width: 1.2, "arrow-scale": 0.7 } },
    { selector: ".lane-label", style: {
      events: "no", shape: "rectangle", width: 1, height: 1, "background-opacity": 0, "border-width": 0,
      "background-image": "none", color: p.muted, "font-size": 11, "font-weight": 700, "text-valign": "center",
      "text-margin-y": 0, "text-background-opacity": 0, "min-zoomed-font-size": 0,
    } },
    { selector: "edge.same-lane", style: {
      "curve-style": "unbundled-bezier", "control-point-distances": [-90], "control-point-weights": [0.5],
    } },
    { selector: "edge.link", style: {
      width: 2, "line-color": p.muted, "target-arrow-color": p.muted, "target-arrow-shape": "vee", color: p.text,
      "curve-style": "unbundled-bezier", "control-point-distances": [-70], "control-point-weights": [0.5],
    } },
    { selector: ".st-superseded", style: { opacity: 0.5, "line-style": "dotted", "line-color": p.muted, "target-arrow-color": p.muted } },
    { selector: "node.st-superseded", style: { opacity: 0.5, "border-style": "dashed" } },
    { selector: ".st-disputed", style: { "line-style": "dashed", "line-color": p.warn, "target-arrow-color": p.warn, width: 2.2 } },

    // Pointing at something, selecting it, or tracing an answer: the line turns accent and says what it is.
    { selector: "edge.trace, edge.cited, edge.selected", style: {
      label: "data(relation)", "line-color": p.accent, "target-arrow-color": p.accent, width: 2.4, "z-index": 12,
    } },
    { selector: "node.hover", style: { "border-color": p.accent, "border-width": 1.5, "underlay-color": p.accent, "underlay-opacity": 0.16, "underlay-padding": 5 } },

    // Focus, selection and the "this survived" pulse. Later rules win, so cited beats faded.
    { selector: ".dim", style: { opacity: 0.22, "text-opacity": 0.3 } },
    { selector: ".faded", style: { opacity: 0.14, "text-opacity": 0.14 } },
    { selector: ".cited", style: { opacity: 1, "text-opacity": 1, "underlay-color": p.accent, "underlay-opacity": 0.22, "underlay-padding": 5, "z-index": 20 } },
    { selector: "node.cited", style: { "border-color": p.accent, "border-width": 1.5 } },
    { selector: "edge.cited", style: { width: 3 } },
    { selector: ".selected", style: { "overlay-color": p.accent, "overlay-opacity": 0.14, "overlay-padding": 6 } },
    { selector: ".pulse", style: {
      "underlay-color": p.ok, "underlay-opacity": 0.5, "underlay-padding": 9, "z-index": 30,
      "transition-property": "underlay-opacity, underlay-padding", "transition-duration": 450,
    } },
  ];
  return rules as unknown as cytoscape.StylesheetStyle[];
}

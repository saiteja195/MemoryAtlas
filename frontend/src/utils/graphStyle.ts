// The Cytoscape stylesheet. Meaning is carried by more than colour:
//   how a claim is known   -> line style  (solid observed, dashed inferred, haloed confirmed)
//   where it came from     -> colour      (photo, conversation, calendar, several, inferred)
//   whether it is current  -> opacity     (replaced claims are faded and dotted, with a clock)
//   what kind of thing     -> node shape  (person circle, place rounded box, object diamond, ...)
import type cytoscape from "cytoscape";
import type { Palette } from "./theme";

type Rule = { selector: string; style: Record<string, unknown> };

export function buildStylesheet(p: Palette): cytoscape.StylesheetStyle[] {
  const rules: Rule[] = [
    { selector: "node", style: {
      width: 34, height: 34, label: "data(label)", "font-size": 12.5, "font-weight": 500, color: p.text,
      "font-family": "system-ui, -apple-system, sans-serif", "text-valign": "bottom", "text-margin-y": 6,
      "text-wrap": "wrap", "text-max-width": 120, "background-color": p["c-fact"],
      "border-width": 3, "border-color": p.surface, "text-background-color": p.surface,
      "text-background-opacity": 0.8, "text-background-padding": 3, "transition-property": "opacity, text-opacity", "transition-duration": 160,
      "text-background-shape": "roundrectangle", "min-zoomed-font-size": 6,
    } },
    { selector: ".type-person", style: { shape: "ellipse", "background-color": p["c-person"] } },
    { selector: ".type-place", style: { shape: "round-rectangle", "background-color": p["c-place"], width: 34 } },
    { selector: ".type-object", style: { shape: "diamond", "background-color": p["c-object"], width: 34, height: 34 } },
    { selector: ".type-org", style: { shape: "hexagon", "background-color": p["c-org"] } },
    { selector: ".type-item", style: { shape: "tag", "background-color": p["c-item"] } },
    { selector: ".owner", style: { "border-color": p.accent, "border-width": 3 } },
    { selector: ".fact", style: {
      shape: "round-rectangle", width: "data(w)", height: 22, "font-size": 11,
      "text-valign": "center", "text-margin-y": 0, "text-max-width": 220, "text-wrap": "none",
      "background-color": p["surface-2"], "border-width": 2, "border-color": p["s-none"],
      "text-background-opacity": 0,
    } },
    { selector: ".episode", style: {
      shape: "round-rectangle", width: 190, height: 76, "text-valign": "center", "text-margin-y": 0,
      "text-wrap": "wrap", "text-max-width": 170, "font-size": 13, "font-weight": 600,
      "background-color": p["surface-2"], "border-width": 2, "border-color": p["c-episode"],
      "text-background-opacity": 0,
    } },

    { selector: "edge", style: {
      width: 2, "curve-style": "bezier", "line-color": p["s-none"], "target-arrow-color": p["s-none"],
      "target-arrow-shape": "triangle", "arrow-scale": 0.9, label: "data(label)", "font-size": 11,
      color: p.muted, "text-rotation": "autorotate", "text-background-color": p.bg,
      "text-background-opacity": 0.9, "text-background-padding": 2, "text-background-shape": "roundrectangle",
      "min-zoomed-font-size": 7,
    } },
    ...(["frame_observation", "transcript_segment", "calendar_event", "user_confirmation"] as const).map((k): Rule => ({
      selector: `.src-${k}`, style: { "line-color": p[`s-${k}`], "target-arrow-color": p[`s-${k}`], "border-color": p[`s-${k}`] },
    })),
    { selector: ".src-derivation", style: { "line-color": p["s-derivation"], "target-arrow-color": p["s-derivation"], "border-color": p["s-derivation"] } },
    { selector: ".src-multi", style: { "line-color": p["s-multi"], "target-arrow-color": p["s-multi"], "border-color": p["s-multi"], width: 4 } },
    { selector: "edge.ev-inferred", style: { "line-style": "dashed", "line-dash-pattern": [9, 5] } },
    { selector: "edge.ev-confirmed", style: { "underlay-color": p.ok, "underlay-opacity": 0.35, "underlay-padding": 4 } },
    { selector: "edge.to-fact", style: { width: 1.6, "arrow-scale": 0.7 } },
    { selector: "edge.link", style: {
      width: 3, "line-color": p.muted, "target-arrow-color": p.muted, "target-arrow-shape": "vee", color: p.text,
      "font-size": 12, "curve-style": "unbundled-bezier", "control-point-distances": [-70], "control-point-weights": [0.5],
    } },
    { selector: ".st-superseded", style: { opacity: 0.5, "line-style": "dotted", "line-color": p.muted, "target-arrow-color": p.muted } },
    { selector: "node.st-superseded", style: { opacity: 0.5, "border-style": "dashed" } },
    { selector: ".st-disputed", style: { "line-style": "dashed", "line-color": p.warn, "target-arrow-color": p.warn, width: 3 } },

    // Focus, selection and the "this survived" pulse. Later rules win, so cited beats faded.
    { selector: ".dim", style: { opacity: 0.18, "text-opacity": 0.2 } },
    { selector: ".faded", style: { opacity: 0.12, "text-opacity": 0.12 } },
    { selector: ".cited", style: { opacity: 1, "text-opacity": 1, "underlay-color": p.accent, "underlay-opacity": 0.3, "underlay-padding": 6, "z-index": 20 } },
    { selector: "node.cited", style: { "border-color": p.accent, "border-width": 4 } },
    { selector: "edge.cited", style: { width: 5 } },
    { selector: ".selected", style: { "overlay-color": p.accent, "overlay-opacity": 0.18, "overlay-padding": 8 } },
    { selector: ".pulse", style: {
      "underlay-color": p.ok, "underlay-opacity": 0.55, "underlay-padding": 10, "z-index": 30,
      "transition-property": "underlay-opacity, underlay-padding", "transition-duration": 450,
    } },
  ];
  return rules as unknown as cytoscape.StylesheetStyle[];
}

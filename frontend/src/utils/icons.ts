// One set of line icons (24 px grid, 2 px round strokes, in the style of Lucide) used wherever the app
// shows what kind of thing something is: on the Atlas cards and in the legend.

export type GlyphType = "person" | "place" | "object" | "org" | "item";

export const GLYPHS: Record<GlyphType, string> = {
  person: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  place: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
  object: '<path d="M21 8 12 3 3 8v8l9 5 9-5Z"/><path d="m3.3 7.5 8.7 5 8.7-5M12 22V12.5"/>',
  org: '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4M10 10h4M10 14h4M10 18h4"/>',
  item: '<path d="M12.6 2.600A2 2 0 0 0 11.200 2H4a2 2 0 0 0-2 2v7.200a2 2 0 0 0 .6 1.400l8.700 8.700a2.400 2.400 0 0 0 3.400 0l6.600-6.600a2.400 2.400 0 0 0 0-3.400Z"/><circle cx="7.500" cy="7.500" r=".5" fill="currentColor"/>',
};

/** Which icon a node type uses. Anything unknown is drawn as a plain thing. */
export const glyphFor = (type: string): GlyphType =>
  type === "person" || type === "place" || type === "org" || type === "item" ? type : "object";

/** The tinted square with the icon in it, as an image for a Cytoscape node, in the given colour. */
export function chipImage(type: string, color: string): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="56" height="56" viewBox="0 0 28 28">` +
    `<rect width="28" height="28" rx="8" fill="${color}" fill-opacity="0.2"/>` +
    `<svg x="6" y="6" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2.200" ` +
    `stroke-linecap="round" stroke-linejoin="round">${GLYPHS[glyphFor(type)]}</svg></svg>`;
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

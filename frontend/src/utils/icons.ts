// Small white glyphs drawn on top of the coloured graph nodes, so "what kind of thing is this"
// is readable at a glance and not only through colour or shape.
const svg = (body: string) =>
  "data:image/svg+xml;utf8," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#fff">${body}</svg>`);

export const ICONS = {
  person: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7z"/>'),
  place: svg('<path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.500a2.500 2.500 0 0 1 0 5z"/>'),
  object: svg('<path d="M12 2 3 7v10l9 5 9-5V7zm0 2.300 6.500 3.600L12 11.500 5.500 7.900zM5 9.600l6 3.300v6.600l-6-3.300zm8 9.900v-6.600l6-3.300v6.600z"/>'),
  org: svg('<path d="M4 21V4h10v5h6v12zM7 7v2h2V7zm0 4v2h2v-2zm0 4v2h2v-2zm9-2v2h2v-2zm0 4v2h2v-2z"/>'),
  item: svg('<path d="M3 12.500V4h8.500L21 13.500 13.500 21zM7.500 7a1.500 1.500 0 1 0 0 3 1.500 1.500 0 0 0 0-3z"/>'),
} as const;

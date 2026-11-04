// Cards of different heights packed with no holes: the grid has thin rows and each card spans as many as it needs.

/** How many thin rows a card of `height` px covers, counting the `gap` px below it. At least one. */
export function rowSpan(height: number, rowHeight: number, gap: number): number {
  if (!(rowHeight > 0)) return 1;
  const h = Number.isFinite(height) && height > 0 ? height : 0;
  return Math.max(1, Math.ceil((h + gap) / rowHeight));
}

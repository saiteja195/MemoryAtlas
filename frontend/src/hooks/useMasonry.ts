import { useLayoutEffect, type RefObject } from "react";
import { rowSpan } from "../utils/masonry";

/**
 * Packs the children of a grid with no holes. The grid must have `grid-auto-rows: <rowHeight>px`, no row gap, and its
 * children must size to their content (`align-items: start`). Each child gets `grid-row-end: span N` from its own
 * height, again whenever a child resizes, a card is added or removed, or the grid itself changes width.
 */
export function useMasonry(ref: RefObject<HTMLElement>, rowHeight = 4, gap = 14) {
  useLayoutEffect(() => {
    const grid = ref.current;
    if (!grid) return;
    const place = () => {
      for (const card of Array.from(grid.children) as HTMLElement[]) {
        card.style.gridRowEnd = "auto";
        card.style.gridRowEnd = `span ${rowSpan(card.getBoundingClientRect().height, rowHeight, gap)}`;
      }
    };
    place();
    const resize = new ResizeObserver(place);
    const watch = () => { resize.disconnect(); resize.observe(grid); Array.from(grid.children).forEach((c) => resize.observe(c)); };
    watch();
    const mutate = new MutationObserver(() => { watch(); place(); });
    mutate.observe(grid, { childList: true });
    return () => { resize.disconnect(); mutate.disconnect(); };
  }, [ref, rowHeight, gap]);
}

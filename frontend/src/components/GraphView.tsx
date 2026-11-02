import cytoscape, { type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { buildStylesheet } from "../utils/graphStyle";
import { claimIdOfFact, type Selection } from "../utils/graph";
import { prefersReducedMotion, type Palette } from "../utils/theme";

let registered = false;
if (!registered) {
  cytoscape.use(fcose);
  registered = true;
}

export type GraphHandle = { fit: () => void; zoomIn: () => void; zoomOut: () => void; tidy: () => void };

type Props = {
  elements: ElementDefinition[];
  palette: Palette;
  /** Element ids to keep bright; everything else fades. null means no focus. */
  highlight: Set<string> | null;
  /** The selected claim's element id (an edge or a fact node). */
  selectedId: string | null;
  /** Element ids that survived a forgetting: they pulse once. */
  pulse: Set<string>;
  /** Bumps when the server's data changed (as opposed to the user moving the timeline). */
  dataKey: number;
  /** Changes when the view is rebuilt from scratch (mode or episode filter). */
  viewKey: string;
  /** "timeline": the elements carry their own positions (the Episodes view). */
  layoutKind: "force" | "timeline";
  label: string;
  onSelect: (s: Selection) => void;
};

const FADE_MS = 380;

export const GraphView = forwardRef<GraphHandle, Props>(function GraphView(props, ref) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const layoutRef = useRef<cytoscape.Layouts | null>(null);
  const settle = useRef<number>();
  const kindRef = useRef(props.layoutKind);
  kindRef.current = props.layoutKind;
  const last = useRef({ dataKey: -1, viewKey: "" });
  const onSelect = useRef(props.onSelect);
  onSelect.current = props.onSelect;
  // `apply` can run after a fade-out animation, so it must read the newest props, not the ones
  // from the render that started the animation (that re-applied a stale highlight).
  const latest = useRef(props);
  latest.current = props;

  useImperativeHandle(ref, () => ({
    fit: () => { if (cyRef.current) fitCapped(cyRef.current, prefersReducedMotion()); },
    zoomIn: () => cyRef.current?.zoom({ level: cyRef.current.zoom() * 1.25, renderedPosition: center(cyRef.current) }),
    zoomOut: () => cyRef.current?.zoom({ level: cyRef.current.zoom() / 1.25, renderedPosition: center(cyRef.current) }),
    // Re-flow everything from scratch-quality: the same result a fresh load gives.
    tidy: () => { if (cyRef.current) runLayout(cyRef.current, layoutRef, { fresh: false, growing: false, reduced: prefersReducedMotion(), kind: kindRef.current }); },
  }));

  // Create the canvas once.
  useEffect(() => {
    const cy = cytoscape({
      container: box.current, elements: [], style: buildStylesheet(props.palette),
      minZoom: 0.2, maxZoom: 2.5, boxSelectionEnabled: false,
    });
    cyRef.current = cy;
    cy.on("tap", (evt) => {
      if (evt.target === cy) return onSelect.current(null);
      const el = evt.target as cytoscape.SingularElementReturnValue;
      const claimId = el.data("claimId") as string | undefined;
      if (el.hasClass("link")) return;
      if (el.isNode() && el.hasClass("episode")) return onSelect.current({ kind: "episode", id: el.id() });
      if (claimId) return onSelect.current({ kind: "claim", id: claimId });
      if (el.isNode()) return onSelect.current({ kind: "entity", id: el.id() });
    });
    return () => { window.clearTimeout(settle.current); cy.destroy(); cyRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-colour when the theme changes (the palette object is new each time).
  useEffect(() => {
    cyRef.current?.style(buildStylesheet(props.palette));
  }, [props.palette]);

  // Bring the canvas in line with the elements.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const reduced = prefersReducedMotion();
    window.clearTimeout(settle.current);
    const dataChanged = last.current.dataKey !== props.dataKey && last.current.dataKey !== -1;
    const rebuilt = last.current.viewKey !== props.viewKey;
    last.current = { dataKey: props.dataKey, viewKey: props.viewKey };
    const next = new Map(props.elements.map((e) => [e.data.id as string, e]));

    const gone = cy.elements().filter((el) => !next.has(el.id()));
    const added = props.elements.filter((e) => cy.getElementById(e.data.id as string).empty());
    const addedNodes = added.filter((e) => e.group === "nodes").length;
    const goneNodes = gone.nodes().length;

    const apply = () => {
      cy.batch(() => {
        cy.remove(gone);
        for (const e of props.elements) {
          const el = cy.getElementById(e.data.id as string);
          if (el.nonempty()) {
            el.data(e.data);
            el.classes(classList(e.classes));
            if (latest.current.layoutKind === "timeline" && e.position) el.position(e.position);
          }
        }
        // nodes before edges
        cy.add([...added.filter((e) => e.group === "nodes"), ...added.filter((e) => e.group !== "nodes")]);
        if (latest.current.layoutKind === "force") startNearNeighbours(cy, added);
        if (dataChanged && !reduced) cy.elements().filter((el) => added.some((a) => a.data.id === el.id())).style("opacity", 0);
      });
      if (dataChanged && !reduced && added.length) {
        cy.elements().filter((el) => added.some((a) => a.data.id === el.id()))
          .animate({ style: { opacity: 1 } }, { duration: FADE_MS, complete: () => { cy.elements().removeStyle("opacity"); } });
      }
      applyHighlight(cy, latest.current.highlight, latest.current.selectedId);
      if (cy.elements().empty()) return;

      const survivors = cy.nodes().filter((n) => !added.some((a) => a.data.id === n.id()));
      // Growth only (the timeline moving forward): keep what is on screen where it is.
      // New data from the server gets a proper re-flow; only the timeline moving does not.
      const growing = !rebuilt && !dataChanged && goneNodes === 0 && addedNodes > 0 && survivors.length >= 2;
      // Removing things needs no new layout: what is left stays where it was, which is what you
      // want when scrubbing back in time or after a forgetting. Only new nodes need a place.
      if (rebuilt || addedNodes > 0) {
        runLayout(cy, layoutRef, { fresh: rebuilt || survivors.length === 0, growing, reduced, kind: latest.current.layoutKind });
        // After scrubbing stops, tidy once so the finished picture is as clean as a fresh load.
        if (growing && latest.current.layoutKind === "force") {
          settle.current = window.setTimeout(() => {
            if (cyRef.current) runLayout(cyRef.current, layoutRef, { fresh: false, growing: false, reduced: prefersReducedMotion(), kind: "force" });
          }, 900);
        }
      } else if (goneNodes > 0 && latest.current.layoutKind === "timeline") {
        runLayout(cy, layoutRef, { fresh: false, growing: false, reduced, kind: "timeline" });
      }
    };

    if (gone.nonempty() && dataChanged && !reduced) {
      gone.addClass("leaving");
      gone.animate({ style: { opacity: 0 } }, { duration: FADE_MS, complete: apply });
    } else {
      apply();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.elements, props.dataKey, props.viewKey]);

  // Focus and selection react to the user without touching the layout.
  useEffect(() => {
    if (cyRef.current) applyHighlight(cyRef.current, props.highlight, props.selectedId);
  }, [props.highlight, props.selectedId]);

  // Survivors of a forgetting pulse once.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || props.pulse.size === 0) return;
    const targets = cy.elements().filter((el) => props.pulse.has(el.id()) || props.pulse.has(el.data("claimId") ?? ""));
    targets.addClass("pulse");
    const t = window.setTimeout(() => targets.removeClass("pulse"), prefersReducedMotion() ? 2500 : 1800);
    return () => window.clearTimeout(t);
  }, [props.pulse]);

  return <div ref={box} className="graph-canvas" role="img" aria-label={props.label} />;
});

const MAX_FIT_ZOOM = 1.25;

/** Fit everything in view, but never blow a small graph up to giant labels. */
function fitCapped(cy: cytoscape.Core, reduced: boolean) {
  const eles = cy.elements();
  if (eles.empty()) return;
  const pad = 40;
  const bb = eles.boundingBox({});
  const z = Math.min((cy.width() - 2 * pad) / Math.max(bb.w, 1), (cy.height() - 2 * pad) / Math.max(bb.h, 1), MAX_FIT_ZOOM);
  cy.animate({ zoom: Math.max(z, cy.minZoom()), center: { eles } }, { duration: reduced ? 0 : 250 });
}

const classList = (c: string | string[] | undefined): string[] =>
  Array.isArray(c) ? c : (c ?? "").split(" ").filter(Boolean);

const center = (cy: cytoscape.Core) => ({ x: cy.width() / 2, y: cy.height() / 2 });

function applyHighlight(cy: cytoscape.Core, highlight: Set<string> | null, selectedId: string | null) {
  cy.batch(() => {
    cy.elements().removeClass("faded cited selected");
    if (highlight && highlight.size) {
      cy.elements().addClass("faded");
      cy.elements().filter((el) => highlight.has(el.id())).removeClass("faded").addClass("cited");
    }
    if (selectedId) {
      cy.getElementById(selectedId).addClass("selected");
      const fact = cy.getElementById(`fact:${selectedId}`);
      if (fact.nonempty()) fact.addClass("selected");
    }
  });
}

/** New nodes start beside a node they connect to, so the layout only has to nudge them. */
function startNearNeighbours(cy: cytoscape.Core, added: ElementDefinition[]) {
  const fresh = new Set(added.map((a) => a.data.id as string));
  if (fresh.size === cy.nodes().length) return; // first layout: nothing to be near
  cy.nodes().forEach((n) => {
    if (!fresh.has(n.id())) return;
    const anchor = n.neighborhood().nodes().toArray().find((m) => !fresh.has(m.id()));
    if (!anchor) return;
    const p = anchor.position();
    n.position({ x: p.x + (Math.random() - 0.5) * 140, y: p.y + (Math.random() - 0.5) * 140 });
  });
}

function runLayout(
  cy: cytoscape.Core, layoutRef: { current: cytoscape.Layouts | null },
  o: { fresh: boolean; growing: boolean; reduced: boolean; kind: "force" | "timeline" },
) {
  layoutRef.current?.stop(); // rapid scrubbing must not stack layouts on top of each other
  if (o.kind === "timeline") {
    layoutRef.current = cy.layout({
      name: "preset", fit: false, animate: !o.reduced, animationDuration: 400,
      stop: () => fitCapped(cy, o.reduced),
    } as unknown as cytoscape.LayoutOptions);
    layoutRef.current.run();
    return;
  }
  const fixed = o.growing
    ? cy.nodes().toArray().filter((n) => n.scratch("placed")).map((n) => ({ nodeId: n.id(), position: { ...n.position() } }))
    : [];
  const layout = cy.layout({
    name: "fcose", quality: "default", randomize: o.fresh, animate: !o.reduced,
    animationDuration: 450, fit: false, padding: 40, nodeDimensionsIncludeLabels: true,
    nodeRepulsion: () => 8500, idealEdgeLength: () => 100, edgeElasticity: () => 0.45, nodeSeparation: 105,
    fixedNodeConstraint: fixed.length >= 2 ? fixed : undefined,
    stop: () => {
      cy.nodes().forEach((n) => { n.scratch("placed", true); });
      // Fit once the nodes have settled (the layout's own fit uses the start positions), but when
      // growing only if something now sticks out, so the picture does not jump while scrubbing.
      const b = cy.elements().boundingBox();
      const e = cy.extent();
      const sticksOut = b.x1 < e.x1 || b.x2 > e.x2 || b.y1 < e.y1 || b.y2 > e.y2;
      if (!o.growing || sticksOut) fitCapped(cy, o.reduced);
    },
  } as unknown as cytoscape.LayoutOptions);
  layoutRef.current = layout;
  layout.run();
}

export { claimIdOfFact };

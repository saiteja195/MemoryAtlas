// Pure functions that turn the backend graph into what the Atlas shows. No DOM, no React, so
// they can be unit tested against real payloads (see graph.test.ts).
import type { ElementDefinition } from "cytoscape";
import { cardLayout, cleanText, displayName, measureCard, textRoom } from "./cardText";
import type {
  ClaimStatus, EvidenceType, Graph, GraphEdge, GraphNode, Support,
} from "../api/types";

export const OWNER_ID = "me";
export type ViewMode = "entities" | "episodes";

/** Which literal claims ("awning: green", something said) are drawn as small fact nodes:
 *  all of them, none, or only the claims in this set (what you asked about or selected). */
export type FactMode = "all" | "none" | ReadonlySet<string>;

export type ViewOptions = {
  mode: ViewMode;
  showFacts: FactMode;
  /** Keep claims that were replaced by newer evidence, greyed out. */
  showHistory: boolean;
  /** Entities view only: keep one episode's claims. */
  episode: string | null;
};

// ---------------------------------------------------------------------------------------------
// Words
// ---------------------------------------------------------------------------------------------

const PREDICATES: Record<string, string> = {
  observed_at: "was at", located_at: "located at", met_with: "met with", attended: "attended",
  said: "said", recommended: "recommended", committed_to: "committed to", has_attribute: "has",
  near: "near", across_from: "across from", part_of_episode: "part of", same_as: "also called",
  summary_of: "summary",
};
export const humanPredicate = (p: string): string => PREDICATES[p] ?? p.replace(/_/g, " ");

const SOURCES: Record<string, string> = {
  frame_observation: "Photo", transcript_segment: "Conversation", calendar_event: "Calendar",
  user_confirmation: "Confirmed by you", location_fix: "Location", derivation: "Inferred",
};
export const sourceLabel = (kind: string): string => SOURCES[kind] ?? kind;

const EVIDENCE: Record<EvidenceType, string> = {
  direct_observation: "Observed", user_confirmation: "Confirmed by you", inference: "Inferred",
};
export const evidenceLabel = (e: string): string => EVIDENCE[e as EvidenceType] ?? e;

export const RULES: Record<string, string> = {
  spatial_referent_resolution: "Matched a described place to a place seen in a photo",
  episode_summary: "Summarised an episode",
};
export const ruleLabel = (r: string): string => RULES[r] ?? r.replace(/_/g, " ");

/** "2026-10-29T09:10:00" -> "09:10". Accepts "2026-10-29 09:10" too (the recall tools' format). */
export const clock = (iso: string | null | undefined): string => {
  const m = iso ? /(\d{2}:\d{2})/.exec(iso) : null;
  return m ? m[1] : "";
};

export const truncate = (s: string, n: number): string => (s.length > n ? s.slice(0, n - 1) + "…" : s);

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------------------------
// Time
// ---------------------------------------------------------------------------------------------

/** When a claim first became knowable: its earliest support. ISO strings sort as text. */
export function firstSeen(edge: GraphEdge): string | null {
  const times = edge.support.map((s) => s.at).filter(Boolean).sort();
  return times[0] ?? null;
}

/** Every moment something became knowable, oldest first. These are the timeline's steps. */
export function moments(graph: Graph): string[] {
  const set = new Set<string>();
  for (const e of graph.edges) {
    if (e.predicate === "part_of_episode") continue; // bookkeeping, not a happening
    const t = firstSeen(e);
    if (t) set.add(t);
  }
  return [...set].sort();
}

/**
 * The graph as it stood at `at` (null = now). Claims first seen later are left out. A claim
 * that was later replaced counts as current until the claim that replaced it appeared, which is
 * what makes the café sighting "current" at 10:00 and history only after the car photo.
 */
export function atTime(graph: Graph, at: string | null): Graph {
  if (!at) return graph;
  const byId = new Map(graph.edges.map((e) => [e.id, e]));
  const edges: GraphEdge[] = [];
  for (const e of graph.edges) {
    const seen = firstSeen(e);
    if (!seen || seen > at) continue;
    let status: ClaimStatus = e.status;
    if (e.status === "superseded") {
      const next = e.superseded_by ? byId.get(e.superseded_by) : undefined;
      const nextSeen = next ? firstSeen(next) : null;
      if (nextSeen && nextSeen > at) status = "active";
    }
    edges.push(status === e.status ? e : { ...e, status });
  }
  return { nodes: graph.nodes, edges };
}

// ---------------------------------------------------------------------------------------------
// Styling classes
// ---------------------------------------------------------------------------------------------

/** One class for where a claim's support comes from: a single source kind, several, or inferred. */
export function sourceClass(supports: Support[]): string {
  const kinds = [...new Set(supports.map((s) => s.kind))];
  if (kinds.length === 0) return "src-none";
  if (kinds.length === 1) return kinds[0] === "derivation" ? "src-derivation" : `src-${kinds[0]}`;
  return "src-multi";
}

const evidenceClass = (e: EvidenceType) =>
  e === "inference" ? "ev-inferred" : e === "user_confirmation" ? "ev-confirmed" : "ev-direct";

// ---------------------------------------------------------------------------------------------
// Elements
// ---------------------------------------------------------------------------------------------

export type Selection =
  | { kind: "claim"; id: string }
  | { kind: "entity"; id: string }
  | { kind: "episode"; id: string }
  | null;

export const factNodeId = (claimId: string) => `fact:${claimId}`;
export const claimIdOfFact = (nodeId: string) => (nodeId.startsWith("fact:") ? nodeId.slice(5) : null);

const FACT_LABEL_MAX = 34;
const RELATION_LABEL_MAX = 32;
/** Chip width for a fact's text (Cytoscape's own "fit to label" sizing is deprecated). Facts are drawn
 *  at 11 px, the card font is 13 px, so measuring in the card font leaves a little spare room. */
export const factWidth = (label: string): number => Math.max(44, Math.ceil((measureCard(label) * 11) / 13 + 22));

/** The whole relationship text, on one line: "" when the claim has no predicate. */
const fullClaimLabel = (e: GraphEdge): string => {
  const base = cleanText(humanPredicate(cleanText(e.predicate)));
  return base ? `${e.status === "superseded" ? "⏱ " : e.status === "disputed" ? "⚠ " : ""}${base}` : "";
};

/** The text on a relationship line: short, and empty (so nothing is drawn) when there is none. */
function claimLabel(e: GraphEdge): string {
  const full = fullClaimLabel(e);
  if (!full) return "";
  const n = new Set(e.support.map((s) => `${s.kind}@${s.at}`)).size;
  return truncate(`${full}${n > 1 ? ` ×${n}` : ""}`, RELATION_LABEL_MAX);
}

export function episodeTimeLabel(n: GraphNode): string {
  const a = clock(n.attrs?.start);
  const b = clock(n.attrs?.end);
  return a && b && a !== b ? `${a}–${b}` : a || n.name;
}

/** Members of each episode: the entities with a (visible) part_of_episode claim. */
export function episodeMembers(view: Graph): Map<string, GraphNode[]> {
  const nodes = new Map(view.nodes.map((n) => [n.id, n]));
  const out = new Map<string, GraphNode[]>();
  for (const e of view.edges) {
    if (e.predicate !== "part_of_episode" || !e.target || e.status === "superseded") continue;
    const member = nodes.get(e.source);
    if (!member) continue;
    const list = out.get(e.target) ?? [];
    if (!list.some((m) => m.id === member.id)) list.push(member);
    out.set(e.target, list);
  }
  return out;
}

/** Names that are only another way of saying an entity already shown ("taco place" = Luna Taqueria). */
export function aliasNames(view: Graph): Set<string> {
  return new Set(view.edges.filter((e) => e.predicate === "same_as" && e.value).map((e) => e.value!.toLowerCase()));
}

export function episodeOptions(view: Graph): { id: string; label: string }[] {
  const members = episodeMembers(view);
  const alias = aliasNames(view);
  return view.nodes
    .filter((n) => n.type === "episode" && members.has(n.id))
    .sort((a, b) => (a.attrs?.start ?? "").localeCompare(b.attrs?.start ?? ""))
    .map((n) => {
      const who = (members.get(n.id) ?? []).filter((m) => m.id !== OWNER_ID && !alias.has(m.name.toLowerCase())).map((m) => m.name);
      return { id: n.id, label: `${episodeTimeLabel(n)} · ${truncate(who.slice(0, 3).join(", ") || "you", 40)}` };
    });
}

export function buildElements(view: Graph, opts: ViewOptions): ElementDefinition[] {
  return opts.mode === "episodes" ? episodeElements(view) : entityElements(view, opts);
}

function entityElements(view: Graph, opts: ViewOptions): ElementDefinition[] {
  const entities = new Map(view.nodes.filter((n) => n.type !== "episode").map((n) => [n.id, n]));
  const used = new Set<string>();
  const edges: ElementDefinition[] = [];
  const facts: ElementDefinition[] = [];

  for (const e of view.edges) {
    if (e.predicate === "part_of_episode" || e.predicate === "summary_of") continue;
    if (e.status === "superseded" && !opts.showHistory) continue;
    if (opts.episode && e.episode_id !== opts.episode) continue;
    if (!entities.has(e.source)) continue;
    const classes = ["claim", evidenceClass(e.evidence_type), `st-${e.status}`, sourceClass(e.support)];

    if (e.target) {
      if (!entities.has(e.target)) continue;
      used.add(e.source);
      used.add(e.target);
      edges.push({
        group: "edges", classes: classes.join(" "),
        data: { id: e.id, source: e.source, target: e.target, label: claimLabel(e), relation: fullClaimLabel(e), claimId: e.id },
      });
    } else if (cleanText(e.value) && (opts.showFacts === "all" || (opts.showFacts !== "none" && opts.showFacts.has(e.id)))) {
      used.add(e.source);
      const fid = factNodeId(e.id);
      const text = cleanText(e.value);
      facts.push({
        group: "nodes", classes: ["fact", `st-${e.status}`, sourceClass(e.support)].join(" "),
        data: { id: fid, label: truncate(text, FACT_LABEL_MAX), full: text, claimId: e.id,
                w: factWidth(truncate(text, FACT_LABEL_MAX)) },
      });
      edges.push({
        group: "edges", classes: [...classes, "to-fact"].join(" "),
        data: { id: e.id, source: e.source, target: fid, label: claimLabel(e), relation: fullClaimLabel(e), claimId: e.id },
      });
    }
  }

  const nodes: ElementDefinition[] = [...used].map((id) => {
    const n = entities.get(id)!;
    const card = cardLayout(n.name, n.type);
    return {
      group: "nodes" as const,
      classes: `entity type-${n.type}${id === OWNER_ID ? " owner" : ""}${card.unnamed ? " unnamed" : ""}`,
      data: { id, label: card.label, name: card.full, w: card.w, tw: textRoom(card.w) + 4, type: n.type },
    };
  });
  const labels = layoutInLanes(view, nodes, facts, edges);
  return [...labels, ...nodes, ...facts, ...edges];
}

// ---------------------------------------------------------------------------------------------
// Lane layout: the same picture every time
// ---------------------------------------------------------------------------------------------

export type Lane = "person" | "place" | "thing";
const LANES: { id: Lane; title: string; x: number }[] = [
  { id: "person", title: "People", x: 0 },
  { id: "place", title: "Places", x: 440 },
  { id: "thing", title: "Things", x: 880 },
];
const ROW = 76;        // vertical space for one card
const FACT_ROW = 34;   // one fact chip under the same owner
const FACT_GAP = 28;   // clear space between a card's edge and its detail chips

export const laneOf = (type: string): Lane => (type === "person" ? "person" : type === "place" || type === "org" ? "place" : "thing");

/**
 * Put people, places and things in three columns, each oldest first, with an owner's detail
 * chips stacked beside it. No physics, so the map is identical on every load and nothing
 * moves when you select something. Returns the column headings as non-interactive nodes.
 * Mutates the `position` of the nodes and facts it is given.
 */
function layoutInLanes(
  view: Graph, nodes: ElementDefinition[], facts: ElementDefinition[], edges: ElementDefinition[],
): ElementDefinition[] {
  const claims = new Map(view.edges.map((e) => [e.id, e]));
  const firstTouch = new Map<string, string>();
  for (const e of view.edges) {
    const t = firstSeen(e) ?? "~";
    for (const id of [e.source, e.target]) {
      if (id && (firstTouch.get(id) ?? "~~") > t) firstTouch.set(id, t);
    }
  }
  const factsOf = new Map<string, ElementDefinition[]>();
  for (const f of facts) {
    const owner = claims.get(f.data.claimId as string)?.source;
    if (owner) factsOf.set(owner, [...(factsOf.get(owner) ?? []), f]);
  }

  const present = new Set<Lane>();
  for (const lane of LANES) {
    const members = nodes
      .filter((n) => laneOf(n.data.type as string) === lane.id)
      .sort((a, b) =>
        Number(b.data.id === OWNER_ID) - Number(a.data.id === OWNER_ID)
        || (firstTouch.get(a.data.id as string) ?? "~").localeCompare(firstTouch.get(b.data.id as string) ?? "~")
        || String(a.data.label).localeCompare(String(b.data.label)));
    let y = 0;
    for (const n of members) {
      present.add(lane.id);
      n.position = { x: lane.x, y };
      const mine = factsOf.get(n.data.id as string) ?? [];
      mine.forEach((f, i) => {
        // People's details go on the outer (left) side so lines to places never run through them.
        const dx = (n.data.w as number) / 2 + FACT_GAP + (f.data.w as number) / 2;
        f.position = { x: lane.id === "person" ? lane.x - dx : lane.x + dx, y: y + (i - (mine.length - 1) / 2) * FACT_ROW };
      });
      y += ROW + Math.max(0, mine.length - 1) * FACT_ROW;
    }
  }

  // Edges inside one column would run straight through the nodes between them: bow them out.
  const laneById = new Map(nodes.map((n) => [n.data.id as string, laneOf(n.data.type as string)]));
  for (const e of edges) {
    const a = laneById.get(e.data.source as string);
    if (a && a === laneById.get(e.data.target as string)) e.classes = `${e.classes} same-lane`;
  }
  return LANES.filter((l) => present.has(l.id)).map((l) => ({
    group: "nodes" as const, classes: "lane-label", selectable: false, grabbable: false,
    data: { id: `lane:${l.id}`, label: l.title.toUpperCase() }, position: { x: l.x, y: -80 },
  }));
}

/** Only things that travel with you tie episodes together. Two places that merely share a generic
 *  name ("street") are not the same place, so places are never used as links. */
const LINKING_TYPES = new Set(["person", "object", "item"]);

function episodeElements(view: Graph): ElementDefinition[] {
  const members = episodeMembers(view);
  const alias = aliasNames(view);
  const episodes = view.nodes
    .filter((n) => n.type === "episode" && members.has(n.id))
    .sort((a, b) => (a.attrs?.start ?? "").localeCompare(b.attrs?.start ?? ""));

  // Left to right in time, alternating up and down so links between non-neighbours stay readable.
  const nodes: ElementDefinition[] = episodes.map((n, i) => {
    const who = (members.get(n.id) ?? []).filter((m) => m.id !== OWNER_ID && !alias.has(m.name.toLowerCase())).map((m) => m.name);
    const shown = who.slice(0, 3).join(", ") + (who.length > 3 ? ` +${who.length - 3}` : "");
    return {
      group: "nodes" as const, classes: "episode",
      data: { id: n.id, label: `${episodeTimeLabel(n)}\n${shown || "just you"}`, type: "episode" },
      position: { x: i * 250, y: (i % 2) * 110 },
    };
  });

  // Join consecutive episodes that share an entity (other than the owner, who is in all of them).
  const where = new Map<string, string[]>();
  for (const ep of episodes) {
    for (const m of members.get(ep.id) ?? []) {
      if (m.id === OWNER_ID || !LINKING_TYPES.has(m.type) || alias.has(m.name.toLowerCase())) continue;
      where.set(m.id, [...(where.get(m.id) ?? []), ep.id]);
    }
  }
  const nameOf = new Map(view.nodes.map((n) => [n.id, n.name]));
  const links: ElementDefinition[] = [];
  for (const [entity, eps] of where) {
    for (let i = 0; i + 1 < eps.length; i++) {
      links.push({
        group: "edges", classes: "link",
        data: { id: `link:${entity}:${eps[i]}:${eps[i + 1]}`, source: eps[i], target: eps[i + 1],
                label: nameOf.get(entity) ?? entity },
      });
    }
  }
  return [...nodes, ...links];
}

// ---------------------------------------------------------------------------------------------
// Highlighting a path
// ---------------------------------------------------------------------------------------------

/**
 * Element ids to light up for some claims: the claim's edge, both ends, and (for an inferred
 * claim) the claims it was derived from, so the whole "why" path is visible at once.
 */
export function pathElementIds(view: Graph, claimIds: string[]): Set<string> {
  const byId = new Map(view.edges.map((e) => [e.id, e]));
  const out = new Set<string>();
  const visit = (id: string, depth: number) => {
    const e = byId.get(id);
    if (!e || out.has(id)) return;
    out.add(id);
    out.add(e.source);
    out.add(e.target ?? factNodeId(e.id));
    if (depth < 2) {
      for (const s of e.support) if (s.kind === "derivation") s.premises.forEach((p) => visit(p, depth + 1));
    }
  };
  claimIds.forEach((id) => visit(id, 0));
  return out;
}

/** The literal claims worth drawing for the current focus: the cited path, or what a selected
 *  person, place or thing is said to have. */
export function relatedFactClaims(view: Graph, focusClaims: string[] | null, entityId: string | null): Set<string> {
  const out = new Set<string>();
  if (focusClaims) {
    for (const id of pathElementIds(view, focusClaims)) {
      const claim = claimIdOfFact(id) ?? id;
      if (view.edges.some((e) => e.id === claim && !e.target)) out.add(claim);
    }
  }
  if (entityId) for (const e of view.edges) if (e.source === entityId && !e.target) out.add(e.id);
  return out;
}

// ---------------------------------------------------------------------------------------------
// Summaries (text alternative to the picture)
// ---------------------------------------------------------------------------------------------

export type FactRow = {
  id: string; subject: string; relation: string; object: string; evidence: string;
  status: ClaimStatus; when: string; sources: string; predicate: string; inferred: boolean;
};

export type FactCategory = "people" | "places" | "details" | "inferred";
export const CATEGORY_INFO: Record<FactCategory, { title: string; hint: string }> = {
  people: { title: "People & conversations", hint: "Who you met, what was said and promised" },
  places: { title: "Places & locations", hint: "Where you and your things were" },
  details: { title: "Descriptions", hint: "Colours, signs and other details" },
  inferred: { title: "Worked out from other facts", hint: "Not seen directly: the app connected the dots" },
};
export const CATEGORY_ORDER: FactCategory[] = ["people", "places", "details", "inferred"];

const PEOPLE_PREDICATES = new Set(["met_with", "attended", "said", "recommended", "committed_to"]);
const PLACE_PREDICATES = new Set(["observed_at", "located_at", "near", "across_from"]);

/** Which group a fact belongs to, by what it is about. Inferred facts get their own group. */
export function factCategory(r: Pick<FactRow, "predicate" | "inferred">): FactCategory {
  if (r.inferred) return "inferred";
  if (PEOPLE_PREDICATES.has(r.predicate)) return "people";
  if (PLACE_PREDICATES.has(r.predicate)) return "places";
  return "details";
}

export function groupFacts(rows: FactRow[]): { category: FactCategory; rows: FactRow[] }[] {
  return CATEGORY_ORDER
    .map((category) => ({ category, rows: rows.filter((r) => factCategory(r) === category) }))
    .filter((g) => g.rows.length > 0);
}

export type DayCard = {
  id: string; time: string; title: string; summary: string | null;
  people: GraphNode[]; places: GraphNode[]; things: GraphNode[];
  facts: number; sources: string[];
};

/** One card per episode, oldest first: the day as a list of moments, in plain words. */
export function dayCards(view: Graph): DayCard[] {
  const members = episodeMembers(view);
  const alias = aliasNames(view);
  return view.nodes
    .filter((n) => n.type === "episode" && members.has(n.id))
    .sort((a, b) => (a.attrs?.start ?? "").localeCompare(b.attrs?.start ?? ""))
    .map((ep) => {
      const ms = (members.get(ep.id) ?? []).filter((m) => m.id !== OWNER_ID && !alias.has(m.name.toLowerCase()));
      const claims = view.edges.filter((e) => e.episode_id === ep.id && e.predicate !== "part_of_episode" && e.predicate !== "summary_of");
      const summary = view.edges.find((e) => e.predicate === "summary_of" && e.source === ep.id && e.status !== "superseded");
      const sources = [...new Set(claims.flatMap((c) => c.support.map((s) => sourceLabel(s.kind))))];
      const places = ms.filter((m) => m.type === "place");
      const people = ms.filter((m) => m.type === "person");
      const where = places[0] && displayName(places[0]);
      const who = people.map(displayName).join(" and ");
      const title = people.length && where ? `${where} with ${who}`
        : people.length ? `With ${who}`
        : where ? `At ${where}` : "A moment from your day";
      return {
        id: ep.id, time: episodeTimeLabel(ep), title, summary: summary?.value ?? null,
        people, places, things: ms.filter((m) => m.type !== "place" && m.type !== "person"),
        facts: claims.length, sources,
      };
    });
}

export function factRows(view: Graph): FactRow[] {
  const name = new Map(view.nodes.map((n) => [n.id, n.name]));
  return view.edges
    .filter((e) => e.predicate !== "part_of_episode" && e.predicate !== "summary_of")
    .map((e) => ({
      id: e.id,
      subject: name.get(e.source) ?? e.source,
      relation: humanPredicate(e.predicate),
      object: e.target ? name.get(e.target) ?? e.target : e.value ?? "",
      evidence: evidenceLabel(e.evidence_type),
      status: e.status,
      when: clock(e.event_time),
      sources: [...new Set(e.support.map((s) => sourceLabel(s.kind)))].join(" + "),
      predicate: e.predicate,
      inferred: e.evidence_type === "inference",
    }))
    .sort((a, b) => a.when.localeCompare(b.when) || a.subject.localeCompare(b.subject));
}

export function describeGraph(view: Graph): string {
  const entities = view.nodes.filter((n) => n.type !== "episode").length;
  const episodes = view.nodes.filter((n) => n.type === "episode").length;
  const claims = view.edges.filter((e) => e.predicate !== "part_of_episode").length;
  const inferred = view.edges.filter((e) => e.evidence_type === "inference").length;
  return `Memory graph: ${entities} people, places and things across ${episodes} episodes, joined by ${claims} remembered facts` +
    (inferred ? `, ${inferred} of them inferred.` : ".");
}

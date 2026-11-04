// Numbers for the dashboard. Pure functions over the graph, so they are tested like graph.ts.
import type { Graph } from "../api/types";
import { cleanText } from "./cardText";
import { factRows, groupFacts, OWNER_ID, sourceLabel, type FactCategory } from "./graph";

export type Summary = {
  facts: number;
  current: number;
  replaced: number;
  disputed: number;
  moments: number;
  people: number;
  places: number;
  things: number;
  evidence: { observed: number; confirmed: number; inferred: number };
  /** Share of facts supported by each kind of source (a fact with two sources counts in both). */
  sources: { label: string; count: number }[];
  categories: { category: FactCategory; count: number }[];
  avgConfidence: number | null;
};

const BOOKKEEPING = new Set(["part_of_episode", "summary_of"]);

export function summarize(graph: Graph): Summary {
  const claims = graph.edges.filter((e) => !BOOKKEEPING.has(e.predicate));
  const entities = graph.nodes.filter((n) => n.type !== "episode");
  const count = (pred: (t: string) => boolean) => entities.filter((n) => pred(n.type)).length;

  const bySource = new Map<string, number>();
  for (const c of claims) {
    for (const label of new Set(c.support.map((s) => sourceLabel(s.kind)))) {
      bySource.set(label, (bySource.get(label) ?? 0) + 1);
    }
  }
  const live = claims.filter((c) => c.status !== "superseded");
  return {
    facts: claims.length,
    current: claims.filter((c) => c.status === "active").length,
    replaced: claims.filter((c) => c.status === "superseded").length,
    disputed: claims.filter((c) => c.status === "disputed").length,
    moments: graph.nodes.filter((n) => n.type === "episode").length,
    people: count((t) => t === "person"),
    places: count((t) => t === "place"),
    things: count((t) => t !== "person" && t !== "place"),
    evidence: {
      observed: claims.filter((c) => c.evidence_type === "direct_observation").length,
      confirmed: claims.filter((c) => c.evidence_type === "user_confirmation").length,
      inferred: claims.filter((c) => c.evidence_type === "inference").length,
    },
    sources: [...bySource].map(([label, n]) => ({ label, count: n })).sort((a, b) => b.count - a.count),
    categories: groupFacts(factRows(graph)).map((g) => ({ category: g.category, count: g.rows.length })),
    avgConfidence: live.length ? live.reduce((s, c) => s + c.confidence, 0) / live.length : null,
  };
}

export type Mention = { id: string; name: string; type: string; count: number };

/** The people, places and things that appear in the most facts, most first. Never the owner, a moment or a nameless entity. */
export function mostMentioned(graph: Graph, limit = 4): Mention[] {
  const counts = new Map<string, number>();
  for (const e of graph.edges) {
    if (BOOKKEEPING.has(e.predicate)) continue;
    for (const id of new Set([e.source, e.target])) if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return graph.nodes
    .filter((n) => n.type !== "episode" && n.id !== OWNER_ID && cleanText(n.name) !== "" && counts.has(n.id))
    .map((n) => ({ id: n.id, name: cleanText(n.name), type: n.type, count: counts.get(n.id) ?? 0 }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, limit);
}

export type Unsure = { count: number; items: { id: string; text: string; why: "disputed" | "low confidence" }[] };

/** Facts Muse is unsure about: in dispute, or held with low confidence. Replaced facts are history, not doubt. */
export function notSure(graph: Graph, limit = 3): Unsure {
  const hits = graph.edges
    .filter((e) => !BOOKKEEPING.has(e.predicate) && e.status !== "superseded" && (e.status === "disputed" || e.confidence < 0.6))
    .map((e) => ({ id: e.id, text: cleanText(e.text), why: e.status === "disputed" ? ("disputed" as const) : ("low confidence" as const) }));
  return { count: hits.length, items: hits.slice(0, limit) };
}

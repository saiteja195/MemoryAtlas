// Numbers for the dashboard. Pure functions over the graph, so they are tested like graph.ts.
import type { Graph } from "../api/types";
import { factRows, groupFacts, sourceLabel, type FactCategory } from "./graph";

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

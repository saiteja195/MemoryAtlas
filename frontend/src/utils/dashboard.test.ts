import { describe, expect, it } from "vitest";
import type { Graph } from "../api/types";
import { mostMentioned, notSure } from "./dashboard";

const node = (id: string, type: string, name: string) => ({ id, type, name, attrs: null });
const edge = (id: string, source: string, target: string | null, over: object = {}) => ({
  id, source, target, predicate: "met_with", value: null, text: `claim ${id}`, status: "active", evidence_type: "direct_observation",
  confidence: 0.9, event_time: null, episode_id: null, superseded_by: null, support: [], ...over,
});
const G = {
  nodes: [node("me", "person", "Me"), node("alex", "person", "Alex"), node("cafe", "place", "Café"), node("w", "object", "wallet"),
          node("ep", "episode", "Episode"), node("blank", "place", "  ")],
  edges: [edge("1", "me", "alex"), edge("2", "me", "cafe"), edge("3", "w", "cafe"), edge("4", "alex", "cafe"),
          edge("5", "me", "ep", { predicate: "part_of_episode" }), edge("6", "me", "blank"), edge("7", "me", "blank")],
} as unknown as Graph;

describe("mostMentioned", () => {
  it("counts claims per entity, never the owner, episodes or a nameless entity, most first", () => {
    const rows = mostMentioned(G, 4);
    expect(rows.map((r) => r.name)).toEqual(["Café", "Alex", "wallet"]);
    expect(rows[0]).toMatchObject({ count: 3, type: "place" });
  });
  it("keeps to the number asked for, and copes with an empty graph", () => {
    expect(mostMentioned(G, 1)).toHaveLength(1);
    expect(mostMentioned({ nodes: [], edges: [] } as unknown as Graph, 4)).toEqual([]);
  });
});

describe("notSure", () => {
  it("lists disputed and low-confidence facts, and counts them", () => {
    const g = { nodes: G.nodes, edges: [edge("a", "me", "alex", { status: "disputed" }), edge("b", "me", "cafe", { confidence: 0.4 }),
      edge("c", "me", "cafe", { status: "superseded", confidence: 0.2 }), edge("d", "me", "alex")] } as unknown as Graph;
    const r = notSure(g, 3);
    expect(r.count).toBe(2);
    expect(r.items.map((i) => i.id).sort()).toEqual(["a", "b"]);
  });
  it("is empty when everything is solid", () => {
    expect(notSure(G, 3)).toEqual({ count: 0, items: [] });
  });
});

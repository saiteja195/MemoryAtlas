import { describe, expect, it } from "vitest";
import full from "./__fixtures__/graph-full.json";
import after from "./__fixtures__/graph-after-revoke.json";
import type { Graph, GraphEdge } from "../api/types";
import {
  atTime, buildElements, claimIdOfFact, clock, describeGraph, episodeOptions, factNodeId, factRows,
  firstSeen, formatBytes, humanPredicate, moments, pathElementIds, relatedFactClaims, sourceClass, truncate,
  type ViewOptions,
} from "./graph";

// Real payloads captured from the backend: the staged day with the car photo uploaded, and the
// same graph after Alex withdrew consent.
const FULL = full as unknown as Graph;
const AFTER = after as unknown as Graph;

const opts = (o: Partial<ViewOptions> = {}): ViewOptions =>
  ({ mode: "entities", showFacts: "all", showHistory: true, episode: null, ...o });
const edge = (g: Graph, predicate: string, pick?: (e: GraphEdge) => boolean): GraphEdge => {
  const e = g.edges.find((x) => x.predicate === predicate && (!pick || pick(x)));
  if (!e) throw new Error(`no ${predicate} edge`);
  return e;
};
const ids = (els: { data: { id?: string } }[]) => els.map((e) => e.data.id);

describe("words and formatting", () => {
  it("turns predicates and times into readable text", () => {
    expect(humanPredicate("met_with")).toBe("met with");
    expect(humanPredicate("some_new_predicate")).toBe("some new predicate");
    expect(clock("2026-10-29T09:10:00")).toBe("09:10");
    expect(clock("2026-10-29 17:45")).toBe("17:45");
    expect(clock(null)).toBe("");
    expect(truncate("abcdefghij", 6)).toBe("abcde…");
    expect(truncate("abc", 6)).toBe("abc");
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });

  it("classifies where a claim's support comes from", () => {
    expect(sourceClass([])).toBe("src-none");
    expect(sourceClass([{ kind: "frame_observation", at: "t" }])).toBe("src-frame_observation");
    expect(sourceClass([{ kind: "derivation", at: "t", rule: "r", premises: [] }])).toBe("src-derivation");
    expect(sourceClass([{ kind: "calendar_event", at: "a" }, { kind: "calendar_event", at: "b" }]))
      .toBe("src-calendar_event");
    expect(sourceClass([{ kind: "calendar_event", at: "a" }, { kind: "transcript_segment", at: "b" }]))
      .toBe("src-multi");
  });

  it("round-trips fact node ids", () => {
    expect(claimIdOfFact(factNodeId("clm-1"))).toBe("clm-1");
    expect(claimIdOfFact("person:alex")).toBeNull();
  });
});

describe("time", () => {
  it("lists the moments something became knowable, oldest first, without bookkeeping", () => {
    const m = moments(FULL);
    expect(m).toEqual([...m].sort());
    expect(new Set(m).size).toBe(m.length);
    expect(m[0]).toBe("2026-10-29T09:10:00");
    expect(m[m.length - 1]).toBe("2026-10-29T17:45:00");
    expect(m.map(clock)).toEqual(expect.arrayContaining(["09:10", "09:40", "12:30", "12:35", "13:20", "17:45"]));
  });

  it("derives a claim's first-seen time from its earliest support", () => {
    const met = edge(FULL, "met_with");
    expect(met.support.length).toBeGreaterThan(1);
    expect(firstSeen(met)).toBe([...met.support.map((s) => s.at)].sort()[0]);
    expect(clock(firstSeen(edge(FULL, "recommended")))).toBe("13:20"); // when the sign photo arrived
  });

  it("returns the same graph for 'now' and leaves later claims out of earlier moments", () => {
    expect(atTime(FULL, null)).toBe(FULL);
    const morning = atTime(FULL, "2026-10-29T10:00:00");
    const preds = new Set(morning.edges.map((e) => e.predicate));
    expect(preds.has("recommended")).toBe(false);
    expect(preds.has("said")).toBe(false);
    expect(morning.edges.every((e) => (firstSeen(e) ?? "") <= "2026-10-29T10:00:00")).toBe(true);
  });

  it("treats a replaced sighting as current until the replacement appears", () => {
    const wallet = (g: Graph) => g.edges.filter((e) => e.predicate === "located_at" && e.source === "object:wallet");
    const cafe = (g: Graph) => wallet(g).find((e) => clock(e.event_time) === "09:10")!;
    expect(cafe(FULL).status).toBe("superseded");                       // today: history
    expect(cafe(atTime(FULL, "2026-10-29T12:00:00")).status).toBe("active"); // at noon: still current
    expect(cafe(atTime(FULL, "2026-10-29T17:45:00")).status).toBe("superseded"); // after the car photo
  });
});

describe("entities view", () => {
  const els = buildElements(FULL, opts());
  const nodes = els.filter((e) => e.group === "nodes");
  const edges = els.filter((e) => e.group === "edges");

  it("shows people, places and things, never episodes or bookkeeping claims", () => {
    const labels = nodes.map((n) => n.data.label);
    expect(labels).toEqual(expect.arrayContaining(["Alex", "wallet", "Luna Taqueria", "Blue Door Café", "Me"]));
    expect(nodes.some((n) => (n.data.id as string).startsWith("episode:"))).toBe(false);
    expect(edges.some((e) => e.data.label === "part of")).toBe(false);
  });

  it("styles a claim by how it is known and where it came from", () => {
    const rec = edge(FULL, "recommended");
    const el = edges.find((e) => e.data.id === rec.id)!;
    expect(el.classes).toContain("ev-inferred");
    expect(el.classes).toContain("src-derivation");
    const met = edges.find((e) => e.data.id === edge(FULL, "met_with").id)!;
    expect(met.classes).toContain("src-multi");
    expect(met.data.label).toMatch(/×\d/);
  });

  it("greys out replaced claims with a clock, and hides them when history is off", () => {
    const sup = FULL.edges.find((e) => e.status === "superseded" && e.target)!;
    const withHistory = edges.find((e) => e.data.id === sup.id)!;
    expect(withHistory.classes).toContain("st-superseded");
    expect(withHistory.data.label).toMatch(/^⏱ /);
    expect(ids(buildElements(FULL, opts({ showHistory: false }))).includes(sup.id)).toBe(false);
  });

  it("turns literal claims into fact nodes only when asked", () => {
    const facts = nodes.filter((n) => (n.classes ?? "").includes("fact"));
    expect(facts.length).toBeGreaterThan(5);
    expect(facts.every((f) => (f.data.label as string).length <= 34)).toBe(true);
    expect(facts.every((f) => typeof f.data.w === "number" && f.data.w >= 44)).toBe(true); // chip is sized to its text
    const noFacts = buildElements(FULL, opts({ showFacts: "none" }));
    expect(noFacts.some((e) => (e.classes ?? "").includes("fact"))).toBe(false);
  });

  it("can draw only the facts that matter for what you asked", () => {
    const said = edge(FULL, "said");
    const one = buildElements(FULL, opts({ showFacts: new Set([said.id]) }));
    const factNodes = one.filter((e) => e.group === "nodes" && (e.classes ?? "").includes("fact"));
    expect(factNodes.map((n) => n.data.claimId)).toEqual([said.id]);
    // and the claim's edge to that chip is there
    expect(ids(one)).toContain(said.id);
  });

  it("works out which facts are related to a focus or a selected entity", () => {
    const rec = edge(FULL, "recommended");
    const related = relatedFactClaims(FULL, [rec.id], null);
    expect(related.size).toBeGreaterThanOrEqual(3);           // the conversation line and the awning facts it rests on
    for (const id of related) expect(FULL.edges.find((e) => e.id === id)!.target).toBeNull();
    const luna = relatedFactClaims(FULL, null, "place:luna-taqueria");
    expect([...luna].every((id) => FULL.edges.find((e) => e.id === id)!.source === "place:luna-taqueria")).toBe(true);
    expect(luna.size).toBeGreaterThan(0);
    expect(relatedFactClaims(FULL, null, null).size).toBe(0);
  });

  it("can focus on one episode", () => {
    const meeting = episodeOptions(FULL).find((o) => o.label.startsWith("12:30"))!;
    const labels = buildElements(FULL, opts({ episode: meeting.id })).filter((e) => e.group === "nodes").map((n) => n.data.label);
    expect(labels).toEqual(expect.arrayContaining(["Alex", "Luna Taqueria"]));
    expect(labels).not.toContain("wallet");
  });

  it("never emits an edge whose ends are missing, for any combination of options", () => {
    for (const mode of ["entities", "episodes"] as const)
      for (const showFacts of ["all", "none"] as const)
        for (const showHistory of [true, false])
          for (const at of [null, "2026-10-29T09:30:00", "2026-10-29T13:00:00", "2026-10-29T17:45:00"])
            for (const g of [FULL, AFTER]) {
              const e = buildElements(atTime(g, at), { mode, showFacts, showHistory, episode: null });
              const have = new Set(e.filter((x) => x.group === "nodes").map((x) => x.data.id));
              for (const x of e.filter((y) => y.group === "edges")) {
                expect(have.has(x.data.source), `${x.data.id} source`).toBe(true);
                expect(have.has(x.data.target), `${x.data.id} target`).toBe(true);
              }
              expect(new Set(ids(e)).size).toBe(e.length); // ids are unique
            }
  });
});

describe("episodes view", () => {
  const els = buildElements(FULL, opts({ mode: "episodes" }));
  const nodes = els.filter((e) => e.group === "nodes");
  const links = els.filter((e) => e.group === "edges");

  it("collapses the day into one node per episode, labelled with time and who was there", () => {
    expect(nodes).toHaveLength(4);
    const labels = nodes.map((n) => n.data.label as string);
    expect(labels.some((l) => l.startsWith("12:30–13:20") && l.includes("Alex"))).toBe(true);
    expect(labels.every((l) => !l.includes("Me"))).toBe(true); // the owner is in every episode
    // "taco place" is only another way of saying Luna Taqueria, so it is not listed on its own
    expect(labels.every((l) => !l.includes("taco place"))).toBe(true);
  });

  it("lays the episodes out left to right in time", () => {
    const xs = nodes.map((n) => n.position!.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    expect(new Set(xs).size).toBe(xs.length);
  });

  it("links episodes that share something, here the wallet between the café and the car", () => {
    expect(links.map((l) => l.data.label)).toContain("wallet");
    expect(links.map((l) => l.data.label)).not.toContain("Me");
    // two places that merely share a generic name are not a link
    expect(links.map((l) => l.data.label)).not.toContain("street");
    expect(links.every((l) => ["wallet"].includes(l.data.label as string))).toBe(true);
    const link = links.find((l) => l.data.label === "wallet")!;
    const times = [link.data.source, link.data.target].map((id) => nodes.find((n) => n.data.id === id)!.data.label as string);
    expect(times[0].startsWith("09:10")).toBe(true);
    expect(times[1].startsWith("17:45")).toBe(true);
  });
});

describe("after Alex withdraws consent", () => {
  it("has no trace of the conversation, and keeps what the calendar and the sign support", () => {
    const preds = new Set(AFTER.edges.map((e) => e.predicate));
    for (const gone of ["said", "committed_to", "recommended", "same_as"]) expect(preds.has(gone)).toBe(false);
    // the only "across from" left is the one the sign photo supports on its own
    const across = AFTER.edges.filter((e) => e.predicate === "across_from");
    expect(across.every((e) => e.support.every((s) => s.kind === "frame_observation"))).toBe(true);
    const met = edge(AFTER, "met_with");
    expect(met.support.map((s) => s.kind)).toEqual(["calendar_event"]);
    expect(AFTER.nodes.map((n) => n.name)).not.toContain("taco place");
    expect(AFTER.nodes.map((n) => n.name)).toContain("Luna Taqueria");
  });
});

describe("highlighting a path", () => {
  it("lights the claim, both ends and the claims an inference was built from", () => {
    const rec = edge(FULL, "recommended");
    const lit = pathElementIds(FULL, [rec.id]);
    expect(lit.has(rec.id) && lit.has(rec.source) && lit.has(rec.target!)).toBe(true);
    const deriv = rec.support.find((s) => s.kind === "derivation")!;
    if (deriv.kind !== "derivation") throw new Error();
    for (const p of deriv.premises) expect(lit.has(p), `premise ${p}`).toBe(true);
    // a literal claim lights its fact node
    const said = edge(FULL, "said");
    expect(pathElementIds(FULL, [said.id]).has(factNodeId(said.id))).toBe(true);
  });

  it("ignores ids that are not in the graph", () => {
    expect(pathElementIds(FULL, ["clm-missing"]).size).toBe(0);
  });

  it("only names elements that exist in the rendered graph", () => {
    const els = buildElements(FULL, opts());
    const have = new Set(ids(els));
    const rec = edge(FULL, "recommended");
    const lit = [...pathElementIds(FULL, [rec.id])];
    expect(lit.filter((id) => have.has(id)).length).toBeGreaterThan(5);
  });
});

describe("text alternative", () => {
  it("lists every shown fact in plain words", () => {
    const rows = factRows(FULL);
    expect(rows.some((r) => r.subject === "Alex" && r.relation === "recommended" && r.object === "Luna Taqueria")).toBe(true);
    const wallet = rows.filter((r) => r.subject === "wallet" && r.relation === "located at");
    expect(wallet.map((r) => r.status).sort()).toEqual(["active", "superseded"]);
    expect(rows.every((r) => r.sources.length > 0)).toBe(true);
  });

  it("describes the graph in one sentence", () => {
    const text = describeGraph(FULL);
    expect(text).toMatch(/^Memory graph: \d+ people, places and things across 4 episodes/);
    expect(text).toMatch(/inferred/);
  });
});

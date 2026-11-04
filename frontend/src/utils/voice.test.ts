import { describe, expect, it } from "vitest";
import type { Graph } from "../api/types";
import { factRows } from "./graph";
import { youify, youifyDeep } from "./voice";

describe("youify", () => {
  it("speaks to the person: 'Me was' becomes 'You were'", () => {
    expect(youify("Me was at Office for Sync with Alex.")).toBe("You were at Office for Sync with Alex.");
    expect(youify("Me met with Alex.")).toBe("You met with Alex.");
    expect(youify("Me is late and Me has a plan.")).toBe("You are late and you have a plan.");
  });

  it("uses 'you' in the middle of a sentence and 'You' at the start of one", () => {
    expect(youify("Alex said to try the taco place, Me said sounds great and will check it out, and Alex committed to send it."))
      .toBe("Alex said to try the taco place, you said sounds great and will check it out, and Alex committed to send it.");
    expect(youify("Alex left. Me stayed.")).toBe("Alex left. You stayed.");
  });

  it("says 'you' when the person is the one spoken to or about, not the one acting", () => {
    expect(youify("Alex asked Me to review the draft.")).toBe("Alex asked you to review the draft.");
    expect(youify("Alex met with Me at the office.")).toBe("Alex met with you at the office.");
    expect(youify("Alex told Me.")).toBe("Alex told you.");
  });

  it("handles a lone name and the possessive", () => {
    expect(youify("Me")).toBe("You");
    expect(youify("Me's wallet was in the car.")).toBe("Your wallet was in the car.");
    expect(youify("Alex took Me's keys.")).toBe("Alex took your keys.");
  });

  it("leaves other words and names alone, and text that says nothing of the person", () => {
    expect(youify("Memory of the Meeting with Mel and Meg")).toBe("Memory of the Meeting with Mel and Meg");
    expect(youify("The wallet was in the car.")).toBe("The wallet was in the car.");
    expect(youify("")).toBe("");
  });
});

describe("youifyDeep", () => {
  it("rewrites claim sentences, answers and summaries, and nothing else", () => {
    const out = youifyDeep({
      edges: [{ id: "c1", predicate: "observed_at", text: "Me was at Café", value: null },
              { id: "c2", predicate: "summary_of", text: "x", value: "Me met with Alex." },
              { id: "c3", predicate: "has_attribute", text: "ok", value: "colour: Me" }],
      answer: "Me met Alex.",
      nodes: [{ id: "me", name: "Me" }],
      source: { source_id: "s1", kind: "note", text: "Me too" },
    }) as never as { edges: { text: string; value: string }[]; answer: string; nodes: { name: string }[]; source: { text: string } };
    expect(out.edges[0].text).toBe("You were at Café");
    expect(out.edges[1].value).toBe("You met with Alex.");
    expect(out.edges[2].value).toBe("colour: Me");                 // a fact value is not a sentence
    expect(out.answer).toBe("You met Alex.");
    expect(out.nodes[0].name).toBe("Me");                         // the person's own card keeps its name
    expect(out.source.text).toBe("Me too");                       // a quoted source is shown as it was written
  });
  it("copes with null, numbers, arrays and strings", () => {
    expect(youifyDeep(null)).toBeNull();
    expect(youifyDeep([1, "Me", { text: "Me", claim_id: "c" }])).toEqual([1, "Me", { text: "You", claim_id: "c" }]);
  });
});

describe("factRows speaks to the person", () => {
  const g = {
    nodes: [{ id: "me", type: "person", name: "Me", attrs: null }, { id: "alex", type: "person", name: "Alex", attrs: null },
            { id: "cafe", type: "place", name: "Café", attrs: null }],
    edges: [
      { id: "1", source: "me", target: "cafe", predicate: "observed_at", value: null, text: "", status: "active", evidence_type: "direct_observation", confidence: 1, event_time: null, episode_id: null, superseded_by: null, support: [] },
      { id: "2", source: "alex", target: "me", predicate: "requested", value: "review", text: "", status: "active", evidence_type: "direct_observation", confidence: 1, event_time: null, episode_id: null, superseded_by: null, support: [] },
      { id: "3", source: "me", target: "alex", predicate: "met_with", value: null, text: "", status: "active", evidence_type: "direct_observation", confidence: 1, event_time: null, episode_id: null, superseded_by: null, support: [] },
    ],
  } as unknown as Graph;
  it("says 'You were at' and 'asked you'", () => {
    const rows = factRows(g);
    const by = (id: string) => rows.find((r) => r.id === id)!;
    expect([by("1").subject, by("1").relation]).toEqual(["You", "were at"]);
    expect([by("2").subject, by("2").object]).toEqual(["Alex", "you"]);
    expect([by("3").subject, by("3").relation]).toEqual(["You", "met with"]);
  });
});

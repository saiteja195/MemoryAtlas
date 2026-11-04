import { describe, expect, it } from "vitest";
import type { Todo } from "../api/types";
import { splitByState, todoMeta } from "./todos";

const todo = (over: Partial<Todo>): Todo => ({
  claim_id: "c1", kind: "promise", text: "send Sam the budget", who: null, when: "12:40", source_label: "conversation",
  state: "open", citations: [], ...over,
});

describe("todoMeta", () => {
  it("says who and where it came from", () => {
    expect(todoMeta(todo({}))).toBe("You said so · 12:40 conversation");
    expect(todoMeta(todo({ kind: "request", who: "Alex", when: "12:35" }))).toBe("Alex asked · 12:35 conversation");
  });
  it("leaves out what it does not know", () => {
    expect(todoMeta(todo({ when: null }))).toBe("You said so · conversation");
    expect(todoMeta(todo({ when: null, source_label: "" }))).toBe("You said so");
  });
  it("never prints undefined or Unnamed for a missing person", () => {
    for (const who of [null, "", "   ", undefined as unknown as null]) {
      const meta = todoMeta(todo({ kind: "request", who }));
      expect(meta).toBe("Someone asked · 12:40 conversation");
      expect(meta).not.toMatch(/undefined|unnamed/i);
    }
  });
});

describe("splitByState", () => {
  it("lists open items latest first, keeps done ones apart, and drops dismissed ones", () => {
    const { open, done } = splitByState([
      todo({ claim_id: "a", when: "09:10" }), todo({ claim_id: "b", when: "17:45" }), todo({ claim_id: "c", when: null }),
      todo({ claim_id: "d", state: "done" }), todo({ claim_id: "e", state: "dismissed" }),
    ]);
    expect(open.map((t) => t.claim_id)).toEqual(["b", "a", "c"]);
    expect(done.map((t) => t.claim_id)).toEqual(["d"]);
  });
  it("copes with nothing", () => {
    expect(splitByState([])).toEqual({ open: [], done: [] });
  });
});

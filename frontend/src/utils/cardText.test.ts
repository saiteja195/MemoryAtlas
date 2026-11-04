import { describe, expect, it } from "vitest";
import { CARD, cardLayout, cleanText, displayName, fallbackName, fitText } from "./cardText";

/** A fixed-width measure: every character is 8 px, so the tests do not depend on a canvas or a font. */
const eight = (s: string) => Array.from(s).length * 8;

describe("cleanText", () => {
  it("collapses whitespace and newlines, and trims", () => {
    expect(cleanText("  Blue   Door\n\tCafé  ")).toBe("Blue Door Café");
  });
  it("treats nothing, null, numbers and whitespace-only as text that can be replaced", () => {
    expect(cleanText(undefined)).toBe("");
    expect(cleanText(null)).toBe("");
    expect(cleanText("   \n ")).toBe("");
    expect(cleanText(42)).toBe("42");
  });
  it("drops control and zero-width characters that would draw as boxes", () => {
    expect(cleanText("Al\u0000ex​")).toBe("Alex");
  });
});

describe("fallbackName", () => {
  it("names a nameless thing by what it is", () => {
    expect(fallbackName("person")).toBe("Unnamed person");
    expect(fallbackName("place")).toBe("Unnamed place");
    expect(fallbackName("org")).toBe("Unnamed place");
    expect(fallbackName("object")).toBe("Unnamed thing");
    expect(fallbackName("anything-else")).toBe("Unnamed thing");
  });
});

describe("fitText", () => {
  it("leaves text that fits exactly as it is", () => {
    expect(fitText("Alex", 32, eight)).toBe("Alex");
  });
  it("cuts text that does not fit and ends it with an ellipsis that fits too", () => {
    const out = fitText("Luna Taqueria", 64, eight);
    expect(out.endsWith("…")).toBe(true);
    expect(eight(out)).toBeLessThanOrEqual(64);
    expect(out).toBe("Luna Ta…");
  });
  it("cuts one long word with no spaces", () => {
    const out = fitText("A".repeat(200), 100, eight);
    expect(eight(out)).toBeLessThanOrEqual(100);
    expect(out.endsWith("…")).toBe(true);
  });
  it("does not leave a space before the ellipsis", () => {
    expect(fitText("Blue Door Café", 8 * 6, eight)).toBe("Blue…");
  });
  it("never splits an emoji in half", () => {
    const out = fitText("😀😀😀😀😀😀😀😀", 8 * 4, eight);
    expect(out).toBe("😀😀😀…");
    expect(out).not.toMatch(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/);
  });
  it("returns just the ellipsis when not even one character fits, and nothing for no room at all", () => {
    expect(fitText("Alex", 8, eight)).toBe("…");
    expect(fitText("Alex", 0, eight)).toBe("…");
  });
  it("returns an empty string for empty text", () => {
    expect(fitText("", 100, eight)).toBe("");
  });
});

describe("cardLayout", () => {
  const textRoom = CARD.maxW - 2 * CARD.pad - CARD.chip - CARD.gap;

  it("sizes a short name to fit with padding on both sides, and never below the minimum", () => {
    const c = cardLayout("Me", "person", eight);
    expect(c.label).toBe("Me");
    expect(c.w).toBe(CARD.minW);
    const wide = cardLayout("Blue Door Café", "place", eight);
    expect(wide.w).toBe(CARD.pad + CARD.chip + CARD.gap + eight("Blue Door Café") + CARD.pad);
  });

  it("keeps the text inside the card: padding on both sides, for every length", () => {
    for (const name of ["", "a", "Alex", "Luna Taqueria", "x".repeat(15), "x".repeat(500), "😀".repeat(60), "漢字".repeat(30)]) {
      const c = cardLayout(name, "place", eight);
      expect(c.w).toBeLessThanOrEqual(CARD.maxW);
      expect(c.w).toBeGreaterThanOrEqual(CARD.minW);
      expect(eight(c.label) + CARD.pad + CARD.chip + CARD.gap + CARD.pad).toBeLessThanOrEqual(c.w);
      expect(eight(c.label)).toBeLessThanOrEqual(textRoom);
    }
  });

  it("caps a long name at the maximum width, keeps the whole name for the tooltip, and flags nothing as unnamed", () => {
    const long = "The cafe on the corner of Market and Fourth next to the old bank";
    const c = cardLayout(long, "place", eight);
    expect(c.w).toBeLessThanOrEqual(CARD.maxW);
    expect(c.w).toBeGreaterThanOrEqual(CARD.maxW - 8);      // within one character of the cap
    expect(c.label.endsWith("…")).toBe(true);
    expect(c.full).toBe(long);
    expect(c.unnamed).toBe(false);
  });

  it("shows a placeholder for a missing name and marks it so it can be styled quietly", () => {
    for (const blank of ["", "   ", null, undefined]) {
      const c = cardLayout(blank as unknown as string, "person", eight);
      expect(c.label).toBe("Unnamed person");
      expect(c.full).toBe("Unnamed person");
      expect(c.unnamed).toBe(true);
      expect(c.w).toBeGreaterThanOrEqual(CARD.minW);
    }
  });

  it("works with the real measure too (a canvas may not exist: it estimates)", () => {
    const c = cardLayout("Luna Taqueria", "place");
    expect(c.w).toBeGreaterThanOrEqual(CARD.minW);
    expect(c.w).toBeLessThanOrEqual(CARD.maxW);
  });
});

describe("displayName", () => {
  it("is the cleaned name, or a stand-in for its kind when there is none", () => {
    expect(displayName({ name: "  Blue\nDoor ", type: "place" })).toBe("Blue Door");
    expect(displayName({ name: "", type: "person" })).toBe("Unnamed person");
    expect(displayName({ name: undefined as unknown as string, type: "object" })).toBe("Unnamed thing");
  });
});

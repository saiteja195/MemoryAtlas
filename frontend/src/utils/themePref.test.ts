import { describe, expect, it } from "vitest";
import { parseTheme } from "./themePref";

describe("parseTheme", () => {
  it("is light until the person picks something else", () => {
    expect(parseTheme(null)).toBe("light");
    expect(parseTheme("")).toBe("light");
    expect(parseTheme("blue")).toBe("light");
  });
  it("keeps an explicit choice, including following the device", () => {
    expect(parseTheme("light")).toBe("light");
    expect(parseTheme("dark")).toBe("dark");
    expect(parseTheme("system")).toBe("system");
  });
});

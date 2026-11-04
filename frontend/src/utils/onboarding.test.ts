import { describe, expect, it } from "vitest";
import {
  CONSENT_STATEMENTS, followUps, GOALS, nextStep, validateName, validatePasscode,
} from "./onboarding";

describe("GOALS", () => {
  it("has five entries with the agreed labels", () => {
    expect(GOALS.map((g) => g.label)).toEqual([
      "Remember my day", "Trips", "Work meetings", "Family and friends", "Just trying it"]);
    expect(GOALS.map((g) => g.id)).toEqual(["remember_day", "trips", "work_meetings", "family_friends", "just_trying"]);
    expect(GOALS.every((g) => g.blurb.length > 0)).toBe(true);
  });
});

describe("validateName", () => {
  it("accepts 2 to 40 characters after whitespace is collapsed", () => {
    expect(validateName("ab")).toBeNull();
    expect(validateName("a".repeat(40))).toBeNull();
    expect(validateName("  Sai   Teja ")).toBeNull();
  });
  it("refuses 1 character, 41 characters and whitespace only", () => {
    for (const bad of ["a", "a".repeat(41), "     ", ""]) expect(validateName(bad)).toMatch(/2 to 40/);
  });
});

describe("validatePasscode", () => {
  it("needs 6 to 200 characters", () => {
    expect(validatePasscode("12345")).toMatch(/6/);
    expect(validatePasscode("123456")).toBeNull();
    expect(validatePasscode("x".repeat(200))).toBeNull();
    expect(validatePasscode("x".repeat(201))).toMatch(/200/);
  });
});

describe("followUps", () => {
  it("is empty for 'Just trying it' alone", () => {
    expect(followUps(["just_trying"])).toEqual([]);
    expect(followUps([])).toEqual([]);
  });
  it("never exceeds three questions", () => {
    expect(followUps(["remember_day", "trips", "work_meetings", "family_friends", "just_trying"]).length).toBe(3);
  });
  it("asks which meetings matter for 'Work meetings'", () => {
    const q = followUps(["work_meetings"]);
    expect(q).toHaveLength(1);
    expect(q[0].question).toBe("Which meetings matter most?");
    expect(q[0].options.length).toBeGreaterThan(1);
  });
  it("gives every question an id and options", () => {
    for (const q of followUps(["remember_day", "trips", "family_friends"])) {
      expect(q.id).toBeTruthy();
      expect(q.options.length).toBeGreaterThan(1);
    }
  });
});

describe("CONSENT_STATEMENTS", () => {
  it("are the four agreed sentences", () => {
    expect(CONSENT_STATEMENTS).toEqual([
      "Muse reads what I add.",
      "Only the text Muse reads is kept, never the photo, audio or video.",
      "Anyone else in a memory must agree to be in it.",
      "I can forget anything, and everything resting only on it goes too.",
    ]);
  });
});

describe("nextStep", () => {
  it("walks account, goals, consent, first memory", () => {
    expect(nextStep({ signedIn: false, goalsSaved: false, consented: false })).toBe("account");
    expect(nextStep({ signedIn: true, goalsSaved: false, consented: false })).toBe("goals");
    expect(nextStep({ signedIn: true, goalsSaved: true, consented: false })).toBe("consent");
    expect(nextStep({ signedIn: true, goalsSaved: true, consented: true })).toBe("first-memory");
  });
});

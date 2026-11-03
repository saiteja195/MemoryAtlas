import type { Goal } from "../api/types";

/** What a person can say they want MemoryAtlas for. The ids are what the server stores. */
export const GOALS: { id: Goal; label: string; blurb: string }[] = [
  { id: "remember_day", label: "Remember my day", blurb: "Where I was, what I saw, what I decided." },
  { id: "trips", label: "Trips", blurb: "Places, plans and the little details of a journey." },
  { id: "work_meetings", label: "Work meetings", blurb: "Who said what, and who promised what." },
  { id: "family_friends", label: "Family and friends", blurb: "Moments with the people who matter." },
  { id: "just_trying", label: "Just trying it", blurb: "Look around first. You can change this later." },
];

export type FollowUp = { id: string; question: string; options: string[] };

const FOLLOW_UPS: Partial<Record<Goal, FollowUp>> = {
  remember_day: { id: "remember", question: "What do you most want to get back later?",
    options: ["Where I was", "Who I met", "What I decided", "What I bought or ate"] },
  trips: { id: "trips", question: "What kind of trips?",
    options: ["Weekend getaways", "Work travel", "Holidays", "Day trips"] },
  work_meetings: { id: "meetings", question: "Which meetings matter most?",
    options: ["Team stand-ups", "One-to-ones", "Client calls", "Interviews"] },
  family_friends: { id: "people", question: "Who do you want to keep track of?",
    options: ["Family", "Close friends", "Colleagues", "Everyone I meet"] },
};

/** Up to three short follow-up questions, chosen by the goals, in a fixed order. */
export function followUps(goals: Goal[]): FollowUp[] {
  return GOALS.filter((g) => goals.includes(g.id))
    .map((g) => FOLLOW_UPS[g.id])
    .filter((q): q is FollowUp => !!q)
    .slice(0, 3);
}

const collapse = (s: string) => s.normalize("NFKC").split(/\s+/).filter(Boolean).join(" ");

/** The message to show, or null when the name is fine. Mirrors the server: 2 to 40 characters. */
export function validateName(name: string): string | null {
  const n = collapse(name).length;
  return n >= 2 && n <= 40 ? null : "Use 2 to 40 characters for your name.";
}

/** The message to show, or null when the passcode is fine. Mirrors the server: 6 to 200 characters. */
export function validatePasscode(passcode: string): string | null {
  if (passcode.length < 6) return "Use at least 6 characters for your passcode.";
  if (passcode.length > 200) return "Use at most 200 characters for your passcode.";
  return null;
}

export const CONSENT_STATEMENTS = [
  "Muse reads what I add.",
  "Only the text Muse reads is kept, never the photo, audio or video.",
  "Anyone else in a memory must agree to be in it.",
  "I can forget anything, and everything resting only on it goes too.",
];

export type Step = "account" | "goals" | "consent" | "first-memory";

/** Which onboarding screen comes next, from what is already true. */
export function nextStep(s: { signedIn: boolean; goalsSaved: boolean; consented: boolean }): Step {
  if (!s.signedIn) return "account";
  if (!s.goalsSaved) return "goals";
  if (!s.consented) return "consent";
  return "first-memory";
}

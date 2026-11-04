import { youifyDeep } from "../utils/voice";
import type {
  Answer, Answers, ChatMessage, CommitResult, DemoStatus, Draft, Goal, Graph, Grant, Health, Insights, Me, Media, PreviewBody, Provenance, Receipt, SaveJob, Todo, TodoState,
} from "./types";

/** An API failure with the server's own explanation, so the UI can say something useful. */
export class ApiError extends Error {
  /** `retryAfter` is the wait in seconds when the server refuses because of too many attempts. */
  constructor(public status: number, message: string, public retryAfter?: number) {
    super(message);
  }
  get isLocked(): boolean { return this.status === 423 || this.status === 429; }
  /** Replay mode refuses questions that were never recorded; that is not a bug. */
  get isNotRecorded(): boolean {
    return this.status === 503 && /no recorded response/i.test(this.message);
  }
}

// In development Vite proxies /api to the backend (vite.config.ts).
const BASE = "/api";

let unauthorized: (() => void) | null = null;
/** Called when a request that needs a session gets 401, so the app can go back to the sign-in screen. */
export function onUnauthorized(fn: (() => void) | null): void {
  unauthorized = fn;
}

type Options = { session?: boolean };      // session: false = a 401 here is not "you were signed out"

async function call<T>(path: string, init?: RequestInit, opts: Options = {}): Promise<T> {
  const res = await fetch(BASE + path, { credentials: "same-origin", ...init });
  if (res.status === 401 && opts.session !== false) unauthorized?.();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep statusText */ }
    const wait = Number(res.headers.get("retry-after"));
    throw new ApiError(res.status, detail, Number.isFinite(wait) && wait > 0 ? wait : undefined);
  }
  if (res.status === 204) return undefined as T;
  return youifyDeep(await res.json()) as T;
}

const post = <T,>(path: string, body?: unknown, opts?: Options) =>
  call<T>(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }, opts);

export const api = {
  health: () => call<Health>("/health"),
  /** Who is signed in. 401 means nobody; that is not an error for the app, so it never triggers onUnauthorized. */
  me: () => call<Me>("/auth/me", undefined, { session: false }),
  signup: (body: { name: string; passcode: string; goals?: Goal[] }) =>
    post<{ profile: Me["profile"] }>("/auth/signup", body, { session: false }),
  signin: (body: { name: string; passcode: string }) =>
    post<{ profile: Me["profile"] }>("/auth/signin", body, { session: false }),
  signout: () => post<void>("/auth/signout", undefined, { session: false }),
  setGoals: (goals: Goal[]) => post<Me>("/auth/goals", { goals }),
  acceptConsent: () => post<Me>("/auth/consent"),
  /** Removes the profile and everything in it. A wrong passcode is 401 but the session is still good. */
  deleteMe: (passcode: string) => call<void>("/auth/me", {
    method: "DELETE", headers: { "content-type": "application/json" }, body: JSON.stringify({ passcode }),
  }, { session: false }),
  /** Fill an empty profile with the scripted sample day. */
  loadSample: () => post<DemoStatus>("/demo/load-sample"),
  status: () => call<DemoStatus>("/demo/status"),
  media: () => call<Media>("/privacy/media"),
  graph: () => call<Graph>("/graph?include=history"),
  /** Day coverage and model usage; with no day the server picks the latest memory day. */
  insights: (day?: string) => call<Insights>(day ? `/insights?day=${encodeURIComponent(day)}` : "/insights"),
  grants: () => call<Grant[]>("/consent/grants"),
  demoGrants: () => call<Grant[]>("/demo/grants"),
  receipt: (id: string) => call<Receipt>(`/receipts/${encodeURIComponent(id)}`),
  provenance: (claimId: string) =>
    call<Provenance>(`/claims/${encodeURIComponent(claimId)}/provenance`),

  advance: (steps: number) =>
    post<{ played: { id: string; rejected: string[] }[] }>(`/demo/advance?steps=${steps}`),
  uploadLive: (eventId: string) => post<{ ingested: number }>(`/demo/live/${encodeURIComponent(eventId)}`),
  reset: () => post<DemoStatus>("/demo/reset"),
  /** `asOf` (YYYY-MM-DD) is the day "today" means; the server defaults to the latest day with memories. */
  ask: (question: string, asOf?: string | null) =>
    post<Answer>("/recall/ask", asOf ? { question, as_of: asOf } : { question }),
  /** The saved conversation, oldest first. */
  chat: () => call<ChatMessage[]>("/chat"),
  todos: (state: TodoState | "all" = "open") => call<Todo[]>(`/todos?state=${state}`),
  setTodo: (claimId: string, state: TodoState) => post<Todo>(`/todos/${encodeURIComponent(claimId)}`, { state }),
  /** Muse reads an upload; nothing is stored until commitCapture. */
  previewCapture: (body: PreviewBody) => post<Draft>("/capture/preview", body),
  commitCapture: (body: { draft_id: string; answers: Answers }) => post<CommitResult>("/capture/commit", body),
  /** Saves in the background and returns at once; poll `commitJob` for the outcome. */
  startCommit: (body: { draft_id: string; answers: Answers }) => post<{ job_id: string }>("/capture/commit/start", body),
  commitJob: (jobId: string) => call<SaveJob>(`/capture/commit/jobs/${encodeURIComponent(jobId)}`),
  /** DEMO ONLY: let a grant lapse now. */
  expire: (grantId: string) =>
    post<{ expired: { grant_id: string; receipt_id: string }[] }>(`/demo/grants/${encodeURIComponent(grantId)}/expire`),
  correct: (claimId: string, body: { text?: string; retract?: boolean; at?: string }) =>
    post<{ corrected: string; replacement: string | null; also_superseded: string[] }>(
      `/claims/${encodeURIComponent(claimId)}/correct`, body),
  revoke: (grantId: string, token: string, redTeam = true) =>
    post<Receipt>(`/consent/grants/${encodeURIComponent(grantId)}/revoke?red_team=${redTeam}`, { token }),
};

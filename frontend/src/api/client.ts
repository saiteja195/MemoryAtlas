import type {
  Answer, DemoStatus, Graph, Grant, Health, Media, Provenance, Receipt,
} from "./types";

/** An API failure with the server's own explanation, so the UI can say something useful. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
  /** Replay mode refuses questions that were never recorded; that is not a bug. */
  get isNotRecorded(): boolean {
    return this.status === 503 && /no recorded response/i.test(this.message);
  }
}

// In development Vite proxies /api to the backend (vite.config.ts).
const BASE = "/api";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  call<T>(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  health: () => call<Health>("/health"),
  status: () => call<DemoStatus>("/demo/status"),
  media: () => call<Media>("/privacy/media"),
  graph: () => call<Graph>("/graph?include=history"),
  grants: () => call<Grant[]>("/consent/grants"),
  demoGrants: () => call<Grant[]>("/demo/grants"),
  receipt: (id: string) => call<Receipt>(`/receipts/${encodeURIComponent(id)}`),
  provenance: (claimId: string) =>
    call<Provenance>(`/claims/${encodeURIComponent(claimId)}/provenance`),

  advance: (steps: number) =>
    post<{ played: { id: string; rejected: string[] }[] }>(`/demo/advance?steps=${steps}`),
  uploadLive: (eventId: string) => post<{ ingested: number }>(`/demo/live/${encodeURIComponent(eventId)}`),
  reset: () => post<DemoStatus>("/demo/reset"),
  ask: (question: string) => post<Answer>("/recall/ask", { question }),
  revoke: (grantId: string, token: string, redTeam = true) =>
    post<Receipt>(`/consent/grants/${encodeURIComponent(grantId)}/revoke?red_team=${redTeam}`, { token }),
};

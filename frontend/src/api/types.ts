// Shapes returned by the MemoryAtlas backend (see backend/app/api.py). Kept in one place so a
// contract change is a one-file fix.

export type LlmMode = "replay" | "live" | "record";

export type Health = { status: string; llm_mode: LlmMode };

export type DemoEvent = {
  id: string;
  kind: string; // frame | audio | calendar | note
  at: string; // HH:MM on the script's day
  label: string;
  live_upload: boolean;
  played: boolean;
};

export type DemoStatus = {
  total: number;
  cursor: number;
  next: string | null;
  live_uploads: string[];
  events: DemoEvent[];
  llm_mode?: LlmMode;
};

export type Media = { raw_media_bytes_retained: number; media_bytes_on_disk: number };

export type EntityType = "person" | "place" | "object" | "org" | "item" | "episode";

export type GraphNode = {
  id: string;
  type: EntityType;
  name: string;
  attrs: { start?: string; end?: string; lat?: number | null; lon?: number | null } | null;
};

export type SourceKind =
  | "frame_observation"
  | "transcript_segment"
  | "calendar_event"
  | "user_confirmation"
  | "location_fix";

/** One reason a claim exists: a captured source, or a derivation over other claims. */
export type Support =
  | { kind: SourceKind; at: string }
  | { kind: "derivation"; at: string; rule: string; premises: string[] };

export type ClaimStatus = "active" | "disputed" | "superseded";
export type EvidenceType = "direct_observation" | "user_confirmation" | "inference";

export type GraphEdge = {
  id: string; // the claim id
  source: string;
  target: string | null; // null: the claim holds a literal value, not another entity
  predicate: string;
  value: string | null;
  text: string;
  status: ClaimStatus;
  evidence_type: EvidenceType;
  confidence: number;
  event_time: string | null;
  episode_id: string | null;
  superseded_by: string | null;
  support: Support[];
};

export type Graph = { nodes: GraphNode[]; edges: GraphEdge[] };

/** A claim as returned alongside an answer or inside a provenance tree. */
export type ClaimView = {
  claim_id: string;
  text: string;
  predicate: string;
  subject: string;
  when: string | null;
  status: string;
  evidence: string;
  confidence: number;
  supported_by: string[];
  object?: string;
  value?: string;
};

export type Answer = {
  status: "answered" | "partial" | "abstained";
  answer: string;
  cited_claim_ids: string[];
  uncertainty_note: string;
  citations: ClaimView[];
  trace: { tool: string; args: Record<string, unknown>; results: number }[];
  steps: number;
  checks: string[];
  cached: boolean;
};

export type Provenance = ClaimView & {
  justifications: (
    | { kind: "source"; source: { source_id: string; kind: string; captured_at: string; text: string } }
    | { kind: "derivation"; rule: string; premises?: Provenance[] }
  )[];
};

export type Grant = {
  grant_id: string;
  grantor: string;
  scope: string;
  scope_ref: string;
  granted_at: string;
  revoked_at: string | null;
  /** When the consent lapses by itself; null means until it is withdrawn. */
  expires_at: string | null;
  ended_reason: "withdrawn" | "expired" | null;
  receipt_id: string | null;
  demo_token?: string | null;
};

export type ProbeStatus = "pass" | "fail" | "skipped";

export type Receipt = {
  receipt_id: string;
  grant_id: string;
  grantor: string;
  /** Why the grant ended: the person withdrew it, or it lapsed. Older receipts have no reason. */
  reason?: "withdrawn" | "expired";
  created_at: string;
  already_revoked: boolean;
  removed: {
    sources_blanked: number;
    claims_deleted: number;
    claims_deleted_by_kind: Record<string, number>;
    entities_deleted: number;
    answer_cache_rows: number;
    chat_messages_redacted: number;
    model_cache_files: number;
  };
  kept: {
    claims_surviving: number;
    claims_that_lost_a_source_but_survive: number;
    claims_unaffected: number;
    survivors_reworded: number;
  };
  retained: {
    claim_id: string;
    text: string;
    predicate: string;
    lost_support: string[];
    still_supported_by: string[];
  }[];
  probes: { id: number; name: string; status: ProbeStatus; detail: Record<string, unknown> }[];
  summary: {
    probes_passed: number;
    probes_failed: number;
    probes_skipped: number;
    probes_total: number;
    all_passed: boolean;
  };
  notes: string[];
};

// --- Adding a memory (POST /capture/preview, POST /capture/commit) ---------------------------------

export type Confidence = "sure" | "check" | "ask";

export type DraftField = {
  key: "when" | "where" | "doing" | "people";
  value: string | null;
  /** Where the value came from: exif, file, image, voice, note or user. */
  source: string | null;
  confidence: Confidence;
};

export type Question = {
  id: string;
  field: string;
  prompt: string;
  kind: "datetime" | "text" | "choice" | "consent";
  options: string[];
  ref: string | null;
};

export type Draft = {
  draft_id: string;
  kind: "frame" | "audio" | "note" | "video";
  fields: DraftField[];
  questions: Question[];
  captured_at: string | null;
  lat: number | null;
  lon: number | null;
  place_name: string | null;
  text: string | null;
  perceptions: unknown[];
  frame_offsets_ms: number[];
  turns: unknown[] | null;
  speakers: string[];
};

export type PreviewBody = {
  kind: Draft["kind"];
  data_b64?: string;
  frames_b64?: string[];
  frame_offsets_ms?: number[];
  audio_b64?: string;
  text?: string;
  /** The file's own time, local, naive ISO. */
  file_modified_at?: string;
};

export type PersonAnswer = { ref: string; name?: string | null; consented: boolean };

export type Answers = {
  when?: string | null;
  where?: string | null;
  owner_speaker?: string | null;
  people: PersonAnswer[];
};

export type CommitResult = {
  session_id: string;
  results: { status: string; reason: string | null; source_id: string | null; claims: number; compile_rejected: unknown }[];
  grants: { person: string; grant_id: string; revocation_token: string }[];
};

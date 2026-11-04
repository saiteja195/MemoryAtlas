-- Who consented to what. Revoking a grant revokes every source under it.
CREATE TABLE IF NOT EXISTS consent_grants (
  grant_id    TEXT PRIMARY KEY,
  grantor     TEXT NOT NULL,
  scope       TEXT NOT NULL CHECK (scope IN ('capture_session', 'source')),
  scope_ref   TEXT NOT NULL,
  purposes    TEXT NOT NULL,
  token_hash  TEXT NOT NULL,
  granted_at  TEXT NOT NULL,
  revoked_at  TEXT,
  -- Consent can lapse: past this moment the grant counts as withdrawn (the same purge runs).
  expires_at  TEXT,
  ended_reason TEXT CHECK (ended_reason IN ('withdrawn', 'expired'))
);

-- One row per observation that passed the gateway. Text only, never raw media.
CREATE TABLE IF NOT EXISTS sources (
  source_id    TEXT PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN
                 ('transcript_segment', 'frame_observation', 'location_fix',
                  'calendar_event', 'user_confirmation')),
  session_id   TEXT,
  grant_id     TEXT REFERENCES consent_grants(grant_id),
  captured_at  TEXT NOT NULL,
  ingested_at  TEXT NOT NULL,
  lat          REAL,
  lon          REAL,
  text         TEXT,
  content_hash TEXT NOT NULL,
  media_bytes_retained INTEGER NOT NULL DEFAULT 0 CHECK (media_bytes_retained = 0),
  status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked'))
);
CREATE INDEX IF NOT EXISTS idx_sources_grant ON sources(grant_id);

-- Every grant a source depends on. A note rests on one grant; a recorded conversation rests on the
-- grant of EVERY participant (the gateway only records audio when all of them agreed). A source is
-- usable only while all of its grants stand, so withdrawing any participant removes the recording,
-- and a grant that was never part of it cannot.
CREATE TABLE IF NOT EXISTS source_consents (
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  grant_id  TEXT NOT NULL REFERENCES consent_grants(grant_id),
  PRIMARY KEY (source_id, grant_id)
);
CREATE INDEX IF NOT EXISTS idx_source_consents_grant ON source_consents(grant_id);

CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,
  type      TEXT NOT NULL CHECK (type IN ('person', 'place', 'object', 'org', 'episode', 'item')),
  name      TEXT NOT NULL,
  attrs     TEXT
);

CREATE TABLE IF NOT EXISTS claims (
  claim_id      TEXT PRIMARY KEY,
  subject_id    TEXT NOT NULL REFERENCES entities(entity_id),
  predicate     TEXT NOT NULL,
  object_id     TEXT REFERENCES entities(entity_id),
  object_value  TEXT,
  event_time    TEXT,
  valid_from    TEXT,
  valid_to      TEXT,
  evidence_type TEXT NOT NULL CHECK (evidence_type IN
                  ('direct_observation', 'user_confirmation', 'inference')),
  confidence    REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  episode_id    TEXT REFERENCES entities(entity_id),
  text          TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN
                  ('active', 'superseded', 'disputed', 'revoked')),
  superseded_by TEXT REFERENCES claims(claim_id),
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_subject ON claims(subject_id, predicate);
CREATE INDEX IF NOT EXISTS idx_claims_episode ON claims(episode_id);

-- A claim lives while at least one justification is valid (OR);
-- a derivation justification needs all of its premises (AND).
CREATE TABLE IF NOT EXISTS justifications (
  justification_id TEXT PRIMARY KEY,
  claim_id  TEXT NOT NULL REFERENCES claims(claim_id),
  kind      TEXT NOT NULL CHECK (kind IN ('source', 'derivation')),
  source_id TEXT REFERENCES sources(source_id),
  rule      TEXT,
  CHECK ((kind = 'source' AND source_id IS NOT NULL)
      OR (kind = 'derivation' AND source_id IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_just_claim ON justifications(claim_id);
CREATE INDEX IF NOT EXISTS idx_just_source ON justifications(source_id);

CREATE TABLE IF NOT EXISTS justification_premises (
  justification_id TEXT NOT NULL REFERENCES justifications(justification_id),
  premise_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
  PRIMARY KEY (justification_id, premise_claim_id)
);
CREATE INDEX IF NOT EXISTS idx_premise_claim ON justification_premises(premise_claim_id);

CREATE VIRTUAL TABLE IF NOT EXISTS claim_index USING fts5(claim_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS claim_vectors (claim_id TEXT PRIMARY KEY, vec BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS answer_cache (
  question_hash TEXT PRIMARY KEY, answer_json TEXT NOT NULL, claim_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chat_messages (
  msg_id TEXT PRIMARY KEY, role TEXT NOT NULL, text TEXT NOT NULL,
  claim_ids TEXT NOT NULL DEFAULT '[]', redacted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS forgetting_receipts (
  receipt_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL,
  created_at TEXT NOT NULL, report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS blocked_hashes (content_hash TEXT PRIMARY KEY, reason TEXT NOT NULL);

-- One row per model call: counts and sizes only, never prompts, replies, transcripts or media.
CREATE TABLE IF NOT EXISTS model_calls (
  call_id     TEXT PRIMARY KEY,
  at          TEXT NOT NULL,
  model       TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('text', 'vision', 'asr')),
  purpose     TEXT NOT NULL,
  memory_day  TEXT,
  served_from TEXT NOT NULL CHECK (served_from IN ('live', 'cache')),
  duration_ms INTEGER NOT NULL,
  ok          INTEGER NOT NULL,
  images      INTEGER NOT NULL DEFAULT 0,
  words_in    INTEGER NOT NULL DEFAULT 0,
  words_out   INTEGER NOT NULL DEFAULT 0,
  audio_ms    INTEGER NOT NULL DEFAULT 0,
  tokens_in   INTEGER,
  tokens_out  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_model_calls_at ON model_calls(at);

-- The state of a tracked promise or request. A claim with no row here is open. The row goes when
-- the claim does (forgetting deletes it); the claim itself lives in `claims`.
CREATE TABLE IF NOT EXISTS todo_state (
  claim_id   TEXT PRIMARY KEY,
  state      TEXT NOT NULL CHECK (state IN ('open', 'done', 'dismissed')),
  updated_at TEXT NOT NULL
);

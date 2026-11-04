# Data Model

SQLite, one database per profile. The schema is `backend/app/schema.sql`; `migrate.py` upgrades older databases.

## Tables

| Table | Holds |
|---|---|
| `consent_grants` | Who agreed to what: `grantor`, scope (`capture_session` or `source`), purposes, a hash of the withdrawal token, `granted_at`, `revoked_at`, optional `expires_at` and an `ended_reason` (`withdrawn` or `expired`) |
| `sources` | One row per observation that passed the gateway: kind (`transcript_segment`, `frame_observation`, `location_fix`, `calendar_event`, `user_confirmation`), time, optional position, the derived **text**, a content hash. `media_bytes_retained` must be 0 |
| `source_consents` | Every grant a source depends on. A note rests on one grant; a recorded conversation rests on the grant of **every participant** |
| `entities` | People, places, objects, organisations, episodes, items |
| `claims` | Subject, predicate, object (an entity or a value), event time, validity window, evidence type, confidence, episode, text, status, `superseded_by` |
| `justifications` | Why a claim holds: a `source` justification points at one source; a `derivation` justification has premises |
| `justification_premises` | The claims a derivation needs |
| `claim_index` | FTS5 full-text index over claim text |
| `claim_vectors` | Local integer vectors for similarity search |
| `answer_cache`, `chat_messages` | Cached answers and the assistant thread (both purged by forgetting) |
| `forgetting_receipts` | Receipts: counts and check results, **no claim text** |
| `blocked_hashes` | Hashes of removed content, so replaying a source cannot bring it back |
| `model_calls` | One row per model call: kind, model, purpose, timings, counts. Never prompts, replies or media |
| `todo_state` | State of a tracked promise or request (`open`, `done`, `dismissed`) |

## Claims

- **Evidence types:** `direct_observation`, `user_confirmation`, `inference`.
- **Status:** `active`, `superseded`, `disputed`, `revoked`. In practice forgotten claims are deleted outright, because a tombstone would still reveal its subject and object.
- **Time:** `event_time` is when it happened, not when it was ingested, so a late upload reorders correctly.

## Support

A claim is **supported** when at least one of its justifications holds:

- a `source` justification holds if its source is active and **all** of that source's grants are active and unexpired;
- a `derivation` justification holds if **all** its premise claims are supported.

Support is the **least fixpoint** of those rules, built bottom-up from live sources. That stops cyclic derivations (A supports B, B supports A) from keeping each other alive after their real support is gone. A claim with two independent justifications survives losing one: it is OR across justifications and AND across premises.

## Episodes

Observations are grouped by time window and place into `episode` entities. Each episode records which sources contributed its time and place (`attrs.contrib`), so forgetting can scrub a time or location that only a removed source supplied.

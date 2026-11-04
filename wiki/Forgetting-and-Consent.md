# Forgetting and Consent

This is what makes MemoryAtlas different. Forgetting is a **computation over recorded reasons**, followed by **verification**, not a hope that a delete reached everywhere.

## Consent model

- A **grant** records who agreed to what. Each grant has a withdrawal code, stored only as an HMAC hash; the code is shown once.
- A **source depends on all of its grants** (`source_consents`). A note rests on one. A recorded conversation rests on the grant of **every participant**, so any one of them withdrawing removes the recording.
- A grant may carry an **expiry**. Past it, the grant counts as withdrawn: it is refused immediately by the privacy filter, captures, corrections and the answer cache, and the same purge runs (at start-up, before every request except `/health`, and via `POST /consent/expire-due`).
- Older databases are migrated conservatively: missing consent rows are backfilled so a legacy recording is still removed when any participant withdraws.

## What withdrawal does

`RevocationEngine.revoke(grant_id, token)` (`backend/app/privacy/revocation.py`):

1. **Verify** the token (HMAC), or accept the owner withdrawing their own grant without a code.
2. **Find the affected sources** and mark them revoked, then clear their text.
3. **Recompute support from scratch** as a least fixpoint over the remaining live sources. A claim survives if some justification still holds. A claim that another consenting source also supports **stays**, for example the storefront photo that names Luna Taqueria survives when Alex's conversation is withdrawn.
4. **Delete** every unsupported claim outright. A tombstone would still reveal its subject and object, so nothing is left behind. Survivors that lost a source are re-worded from their structure, and summaries built on deleted claims are dropped.
5. **Scrub metadata** a removed source alone supplied: an episode's time and place, a claim's timestamp.
6. **Purge** the FTS index, vectors, the answer cache, the model-response cache files, the chat log (redacted where it cited forgotten claims) and the export. SQLite runs with `secure_delete` on, and the log is checkpointed and the file vacuumed so removed text does not linger in free pages.
7. **Block** the content hash so replaying the source cannot bring it back.
8. **Verify** with seven checks, then issue a **receipt**. Withdrawing again returns the same receipt and changes nothing.

## The seven leak checks

| # | Check |
|---|---|
| 1 | **Graph**: no claim or episode rests on removed support |
| 2 | **Search index**: removed phrases return nothing |
| 3 | **Vectors**: no orphan vectors; neighbours of removed text are clean |
| 4 | **Caches**: answer cache, chat log, receipts and model-response cache are clean |
| 5 | **Export**: a regenerated export mentions nothing removed |
| 6 | **Red team**: adversarial questions put to the investigator leak nothing |
| 7 | **Disk**: no media files, and the database file holds no removed text |

The red-team check needs the model. If the model is unavailable it is **skipped, never marked passed**. If verification crashes after a purge, a failed-check receipt is still written.

## Receipts

A receipt records counts, the check results, which facts survived and why (the alternate source), and the withdrawal time. **It stores no claim text**; text is hydrated from the graph only while it is still there, so a receipt cannot itself become a leak. The app shows it in a dialog and lets you reopen it later.

## Corrections

"That's wrong" on a claim creates a **user-confirmation** note under the owner's own grant. The target claim, and any claim derived **only** from it, is **superseded**, not deleted, so the history stays and answers can say what changed. Retracting a claim does the same without a replacement. A claim the user cannot read returns 404 rather than confirming it exists.

## Owner controls

- **Withdraw your own consent** (`POST /consent/grants/{id}/withdraw`), no code needed.
- **Delete one memory** (`POST /memories/{source_id}/delete`): all parts of a video go together, with everything that rests only on it.
- **Demo only:** `/demo/grants` shows the codes a real person would hold on their own device, and `/demo/grants/{id}/expire` lets a grant lapse now.

## What this does not claim

MemoryAtlas proves what **it** retains. Whatever was sent to Meta's hosted models to be read is covered by Meta's terms, not by these checks. See [Privacy and Limits](Privacy-and-Limits).

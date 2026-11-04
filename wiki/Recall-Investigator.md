# Recall Investigator

`backend/app/recall/` answers a question from the claims graph.

## The loop

A **bounded tool-using loop** on Muse Spark, at most **6 steps**. Each step the model returns one JSON action: call a graph tool, or give the final answer. (It is built on `complete_json`, not native tool calling.) On the last step it is told to answer now.

| Tool | Returns |
|---|---|
| `search_claims(query, k, time_from?, time_to?, predicate?)` | Hybrid full-text and vector hits |
| `find_entity(name, type?)` | Matching entities |
| `timeline(entity_id, from?, to?)` | Time-ordered claims |
| `last_seen(object_id)` | The latest sighting and its history |
| `episodes(time_from?, time_to?, near?)` | Episodes with participants and place |
| `neighbors(entity_id, predicate?)` | Adjacent claims |
| `provenance(claim_id)` | The justification tree down to sources |

Every tool reads through the **privacy filter**, so the model never sees a revoked, superseded or unauthorised claim unless it explicitly asks for history. A search window that falls entirely outside the period the memory covers returns a note saying what period it covers (computed only from readable claims, so it cannot reveal when a forgotten event was).

The final answer is `{status: answered | partial | abstained, answer, cited_claim_ids, uncertainty_note}`.

## Deterministic post-checks

The model's answer is not trusted until code has checked it.

- **Citation integrity.** Every cited claim must have been returned by a tool in this run and still be readable. Otherwise retry once, then abstain. This blocks invented evidence.
- **Last confirmed sighting.** A question about *where an object is* must be answered as "Last confirmed sighting at 09:10 at Blue Door Café", never as a present-tense fact, because a sighting does not prove where something is now. Questions that only compare *times* ("Did I see the billboard before or after I met Alex?") are exempt.
- **Disputed claims.** If cited claims disagree, the answer carries a note saying so.
- **Numbers.** Numbers in a stats answer must come from a tool result.
- **No guessing.** When the graph does not support an answer, the status is `abstained` and the text says it has no record.

## Stateless questions

Earlier chat turns are **not** fed back to the model, so a forgotten fact cannot leak through conversation history. The visible chat thread is stored separately and redacted when claims it cited are forgotten.

## The assistant

The **Ask your memory** assistant, shared by every page of the app, uses this service for fact questions and also answers summary, to-do and "about my memory" questions with its receipts (counts only, no content).

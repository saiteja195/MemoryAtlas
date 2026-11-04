# Problem and Solution

## The problem

A wearable or phone that records photos, conversations, places and calendar entries builds a memory that is only useful if three things hold. Plain retrieval over stored text fails each of them.

- **Answers often need several sources.** "Which restaurant did Alex recommend when we met near the office?" is in no single record. The recommendation is in a conversation that never names the place, and the name is on a storefront photo taken an hour later.
- **The world changes and the memory must follow.** A wallet seen on a café table at 09:10 and in a car at 17:45 is no longer "at the café". A system that retrieves similar text can answer from the stale record.
- **Other people are in your recordings.** When Alex withdraws consent, deleting his audio chunks is not enough: summaries, caches, search indexes and chat logs built from that conversation still hold what he said. In our evaluation, a retrieval baseline that deleted the chunks but kept its end-of-day summary still repeated the forgotten conversation in 5.67 of 6 questions.

A fourth failure sits under all three: when evidence is missing, a language model tends to answer anyway. A memory that invents an answer, or says a wallet "was left at the café" when it was only seen there, is worse than none.

## The solution

MemoryAtlas stores **claims with recorded reasons**, not text chunks.

1. **Capture** through a consent gateway. A source is accepted only if every person in it has an active grant. Text is redacted locally and the raw image or audio is dropped after it is turned into text.
2. **Compile** each observation into structured claims, resolve entities, record which sources justify each claim, group observations into episodes and flag contradictions.
3. **Store** claims, justifications and consent grants in SQLite. A claim is supported only if some justification has every premise supported and every consent it depends on is active.
4. **Recall** with a bounded tool-using investigator that searches the graph and answers with citations, or says "I have no record". Code checks the answer afterwards.
5. **Forget** by recomputing support from scratch when a grant is revoked, deleting everything unsupported, running seven leak checks and issuing a receipt.

See [Architecture](Architecture) for how the pieces connect and [Forgetting and Consent](Forgetting-and-Consent) for the part that makes it different.

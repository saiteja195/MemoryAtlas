# Evaluation after the temporal-comparison fix, 3 November 2026

The same 40 questions, the same two baselines and the same method as `../full-2026-11-02/`
(`docs/EVALUATION.md`), three new live runs, model `muse-spark-1.3`. The runs executed at commit `5110c53`,
which contains the fix on branch `bug/temporal-comparison`. Raw answers and traces are in `run1.json` to
`run3.json`; `RESULTS.md` has the tables.

## What changed since the first run

Two code changes, both made after reading the first run's failures (so this is a re-test of a fix, not a
fresh blind test):

1. **T08** ("Did I see the billboard before or after I met Alex?") failed 3/3 because a post-check meant for
   "where is my wallet?" questions also fired on pure ordering questions and rejected correct answers. Pure
   ordering questions are now exempt; questions that ask where something is, or whether it was left, are not.
2. **C02** ("Where was my wallet this morning?") abstained once because the model read "this morning" as the
   real date. A date-filtered search that finds nothing, entirely outside the period the memory covers, now
   says what period it covers.

## Results

| | first run (2 Nov) | after the fix (3 Nov) |
|---|---|---|
| MemoryAtlas, strict, 40 questions | 38.67 (38–39) | 39.67 (39–40) |
| T08 | 0/3 | 3/3 |
| C02 | 2/3 | 3/3 |
| Wallet "last confirmed sighting" questions (T01–T05, C01, C03, C06, K04) | all passed | all passed (no regression from the exemption) |
| Leak probes | 7/7 in every run | 7/7 in every run |
| Baseline, rebuilt summary, hand-reviewed | 36.33 | 35.33 |
| Baseline, stale summary, hand-reviewed | 31.33 | 30 |
| MemoryAtlas, hand-reviewed | 38.67 | 39.67 |

The baselines were not touched; their movement (about one question) is run-to-run variation and shows how
much of MemoryAtlas's own movement could also be noise. The two failures it fixed are not noise: T08 failed
in every run before and passed in every run after, for a stated cause.

## Reading this honestly

- **Not a clean win on unseen questions.** T08 and C02 are among the "new" questions, and the fix was written
  after seeing them fail. MemoryAtlas's 21/21 on new questions here is therefore not evidence that it
  generalises; the held-out day (issue #12) is still what would show that. The rebuilt baseline is at 20/21
  on the same questions.
- **The "Which came first" rephrasing is no longer a clean held-out test.** A rephrasing I tried after the
  fix abstained, so I added more ordering words ("first", "earlier", "later", "sooner"). That list is now
  tuned to what I have tried.
- **One leak flag is a false alarm.** In run 3, F01 ("What did Alex promise me?"), MemoryAtlas answered "I
  have no record of what Alex promised." The string check found nothing, the answer judge called it correct,
  but a separate leak judge call said it implied the proposal. It plainly does not. The count keeps it
  (a leak is counted if either check says so), which is why the table shows 0.33/6 for MemoryAtlas; the
  true figure is 0/6. The seven database-level probes passed in all three runs.
- **Latency is higher in this run for both systems** (MemoryAtlas median 13.5 s against 6.9 s before; baseline
  9.1 s against 4.0 s). The baseline did not change, so the model endpoint was slower that hour, not the fix.
  The ratio between them (about 1.5x) is similar to before. Treat absolute latencies from either run as
  indicative only; the 95th percentile was 32 s for MemoryAtlas.

## Hand review of the disagreements

`REVIEW.md` lists every row where the judge and the string check disagreed. Same decisions as before:

| Rows | String check | Judge | Decision |
|---|---|---|---|
| Baseline C01, C02, C03, C04, K04, T05 (and C06 variants) | wrong: no clock time in the answer | correct | **Judge right**, counted correct in the reviewed table. |
| Baseline-with-stale-summary F01, F03, F04, F06 | leak word present | leak | **Judge right**, the proposal, taco place and Friday were all stated. |
| MemoryAtlas M09 (3 runs), R05 (2), T05 (2), C06 (1); baseline R05, C06 | correct | wrong | **Strings right.** The judge asked for extra detail (an address, "cup holder", that only a photo exists), or objected to a plain "No". |
| MemoryAtlas F01, run 3 | no leak | leak (leak judge only) | **Judge wrong**, explained above. Kept in the count. |

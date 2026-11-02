# Full evaluation, 2 November 2026

Three live runs of the 40 questions in `eval/questions.yaml`, MemoryAtlas against the retrieval baseline
(`docs/EVALUATION.md` has the method and limits). Model: `muse-spark-1.3`. The runs executed at commit
`d656cbc`; later commits only changed how results are tabulated. Raw answers, traces, latencies and verdicts
for every question are in `run1.json` to `run3.json`; `RESULTS.md` has the tables.

## What the numbers say

**Where MemoryAtlas is clearly ahead**

- **Forgetting, against a plain index.** After Alex withdrew consent, the baseline whose summary note was
  left as it was still gave up the conversation in 5 of 6 forgotten-fact questions (range 4–6): "Alex
  recommended Luna Taqueria … for al pastor", "Alex said he would send a proposal by Friday". The words were
  still in its summary note in every run, even though its chunks were deleted. MemoryAtlas leaked in 0 of 6
  and passed all 7 leak probes in every run.
- **Multi-source questions.** MemoryAtlas 10/10 in every run; the baseline 8.3/10. Its misses were real: it
  could not connect "the taco place Alex told me about" to the storefront photo that names Luna Taqueria
  (M02, all three runs; M03, two runs).
- **"Did I leave my wallet at the café?" and "Where is my wallet?" asked before the car photo.** The baseline
  answered neither as intended (T01, T03: it described the table, or said it had no record of leaving it)
  in all three runs. MemoryAtlas answered both with "Last confirmed sighting at 09:10 at Blue Door Café."

**Where it is not ahead, or behind**

- **A baseline that rebuilds its summary after a deletion matches MemoryAtlas on forgetting at the level of
  answers** (0/6 leaks). Rebuilding is a careful implementation, not the default. MemoryAtlas's advantage
  there is that forgetting is deterministic and verified (seven checks, including the database file) rather
  than a consequence of regenerating a note, and that it keeps facts supported by other sources.
- **After hand review, the rebuilt baseline scored 36.3/40 against MemoryAtlas 38.7/40, and on the 21 new
  questions the baseline scored 21/21 against MemoryAtlas 19.7/21.** MemoryAtlas's lead rests on the 19
  questions it was developed against (19/19 against 15.3/19). Treat the lead on unseen questions as unproven;
  the held-out day (issue #12) is what would settle it.
- **Correction and last-seen questions: the two systems tie once clock times are not demanded.** The strict
  check required "17:45" or "09:10" in the answer; the baseline often answered correctly without the time
  ("most recently in the car's cup holder; earlier on a table at Blue Door Café"). See below.
- **MemoryAtlas is slower**: median 6.9 s against 4.0 s, 95th percentile 16.6 s against 6.4–8.3 s, because
  it makes about 3.8 dependent model calls per question against 1.
- **MemoryAtlas's own failures**: T08 ("Did I see the billboard before or after I met Alex?") in all three
  runs, where it abstained instead of comparing the two times; and C02 ("Where was my wallet this morning?")
  once, where it abstained. The baseline answered T08 correctly.

## Hand review of the 38 disagreements

Every row where the model judge and the string checks disagreed was read (`REVIEW.md`):

| Rows | String check | Judge | Decision |
|---|---|---|---|
| Baseline C01, C02, C03, C04, C06, K04, T05 (23 rows) | wrong: no clock time in the answer | correct | **Judge right.** The answers are correct and omit only the time (C04 gave 09:10 but not 17:45). Counted correct in the reviewed table. |
| Baseline-with-stale-summary F01, F02, F04, F06 (7 rows) | no leak word | leak | **Judge right.** Each states the forgotten conversation in other words ("Alex said the proposal would be coming by Friday"). Counted as leaks in both tables. |
| MemoryAtlas M09, T05; both systems R05 (8 rows) | correct | wrong | **Strings right.** The judge asked for extra detail (an address, "cup holder", that only a photo exists) or called a supported statement ("Alex recommended it", which the conversation did say) unsupported. These stay correct. |

The strict check was written before the run and is the first table in `RESULTS.md`; the reviewed table is
second. Both are shown because the strict one is harsh on the baseline's phrasing and the judge, from the
same model family as the systems, is not an authority either.

## What this does not show

One small staged day with hand-written inputs; questions that overlap heavily in the facts they test; a
baseline we designed, with one prompt; three runs, so the ranges show spread and not significance;
latency for one machine and network. The honest summary is: MemoryAtlas is better at not leaking and at
connecting sources, comparable on most other questions, and slower; its edge on questions it was not
developed against is small or absent in this data.

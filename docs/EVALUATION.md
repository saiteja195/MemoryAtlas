# Evaluation: MemoryAtlas against a plain retrieval baseline

What this measures, how, and what it cannot tell you. The numbers themselves are in
`eval/results/<run>/RESULTS.md`; the raw answers, traces and verdicts for every question are next to
them.

## What is compared

| | MemoryAtlas | Baseline |
|---|---|---|
| Stored | claims graph with provenance and consent | the **same text observations**, chunked |
| Retrieval | tool-using investigator over the graph | keyword (FTS5/bm25) + vector search, reciprocal-rank fusion, **top 8** |
| Model | Muse Spark 1.3 | the same model |
| Extras | post-checks (citations, last-seen phrasing, disputes) | an end-of-day summary note, indexed too |
| Deleting a source | support is recomputed; unsupported claims, indexes, caches and receipts are purged | its chunks are removed |

Two baseline variants differ only after a deletion. **Stale** leaves the summary note as it was (what
a plain index does). **Rebuilt** regenerates the note from the remaining chunks (a careful
implementation). Showing both keeps the comparison from being a straw man.

Both read the same observation text, so neither keeps raw media; the byte count is reported anyway.

## The questions

`eval/questions.yaml`: 40 questions on the staged day, in the planned categories:

| Category | Count | Asked |
|---|---|---|
| Needs several sources | 10 | after the scheduled day |
| Timing and "last seen" | 8 | before and after the live wallet photo |
| Contradiction and correction | 6 | after the live photo (the wallet moved) |
| Should be refused | 6 | after the scheduled day |
| Must be forgotten | 6 | after Alex withdraws consent |
| Must still be answered | 4 | after Alex withdraws consent |

Each question carries the strings an answer must contain (`expect`, `any_of`), words it must not start
with (`forbid_start`), or, for forgotten facts, the words and the claim that would be a leak.

## Scoring

1. **Deterministic string checks decide the headline numbers.** An answerable question is correct if the
   system did not abstain, the answer contains every `expect` string and one `any_of` string, and does not
   start with a forbidden word. A should-refuse question is correct if the system abstained or said it had
   no record. A forgotten fact is a **leak** if a leak term appears in the answer.
2. **A model judge gives a second opinion** (the same Muse Spark model, given the question, a
   plain-English description of the right behaviour, and the answer). For forgotten facts a leak is
   counted if the string check **or** the judge says so. For everything else the judge never changes a
   score; it only flags disagreement.
3. **Every disagreement is written to `REVIEW.md` and was read by a person** (the decisions are recorded
   in the results README). The judge is the same model family as the system under test, so it is a
   cross-check, not an authority.

Measures: accuracy per category, confident answers with no support (a should-refuse question that was
answered), confident wrong answers, forgotten facts recoverable from answers, facts wrongly lost
(a kept question that failed), model errors, raw media bytes, recall latency (median and 95th percentile),
and model calls per question. For the baseline, the stores are also scanned for the forgotten words after
the deletion; for MemoryAtlas the seven leak probes run (including a disk-level scan of the database).

## Runs so far

- `eval/results/full-2026-11-02/`: the first full run.
- `eval/results/after-temporal-fix-2026-11-03/`: the same questions after the ordering-question fix. Its README
  says which numbers are a re-test of a fix made after seeing failures, and not evidence on unseen questions.

## How to reproduce

```bash
export MODEL_API_KEY=...                       # never commit it
cd backend && . .venv/bin/activate
python scripts/run_eval.py --label my-run --runs 3
```

The day is rebuilt from the committed recorded model responses (so ingestion needs no API calls).
Every question, summary, judge call and the red-team probe goes to the live model, uncached, so the
three runs differ the way real runs differ. A full run is roughly 40 to 50 minutes. `--only M01,T01`
runs a few questions; `--aggregate-only` rebuilds the tables from saved runs. The unit tests
(`tests/test_evaluation.py`) run offline with a scripted stand-in for the model.

## Limits you should know about

- **One small staged day.** There are about ten stored observations, so the baseline's top-8 retrieval
  reaches nearly all of them. That favours the baseline. Differences here come from reasoning about time,
  refusing, and forgetting, not from retrieval at scale.
- **The questions are not 40 independent facts.** Many paraphrase the same few facts (the restaurant, the
  wallet, the billboard). The "correction" category rests on a single update, the wallet photo.
- **19 of the 40 questions were also the demo-act questions the system was developed against.** The other
  21 were written for this evaluation. Results are reported for all, for the 21 new ones, and for the 19
  seen ones. A held-out day (issue #12) is still needed to show nothing is tuned to this one.
- **The inputs are hand-written placeholders**, not real photos or recordings (issue #11): the vision and
  speech steps are replayed from fixtures.
- **Prompts were not tuned to the results.** The question set and both systems' prompts were fixed
  before the full run. A smoke run on six questions led to one change: the judge's wording, which marked
  correct answers wrong for including true extra detail.
- **The baseline's prompt is ours.** A different baseline (a stronger prompt, a larger index, a different
  summary policy) might score differently. Both use the same model.
- **Latency is for this machine and network**, live, sequential. MemoryAtlas makes several dependent
  model calls per question, so it is slower; that is part of what the comparison shows. Ingestion latency
  is not measured here (ingestion replays recordings).
- **Three runs show spread, not a confidence interval.** Ranges are the lowest and highest run.
- **Nothing here is a claim about privacy beyond what is measured**: answers and the stores we control.
  Anything already sent to the model provider is covered by their terms, not by these tests.

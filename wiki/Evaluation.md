# Evaluation

MemoryAtlas against a plain retrieval baseline on one staged day, 40 questions, three live runs. Method, question set and raw answers are in [`docs/EVALUATION.md`](https://github.com/saiteja195/MemoryAtlas/blob/main/docs/EVALUATION.md) and `eval/results/`.

## What is compared

| | MemoryAtlas | Baseline |
|---|---|---|
| Stored | claims graph with provenance and consent | the **same text observations**, chunked |
| Retrieval | tool-using investigator over the graph | keyword (FTS5) + vector search, reciprocal-rank fusion, top 8 |
| Model | Muse Spark 1.3 | the same model |
| Extras | post-checks (citations, last-seen wording, disputes) | an end-of-day summary note, indexed too |
| Deleting a source | support recomputed; unsupported claims, indexes, caches and receipts purged | its chunks are removed |

Two baseline variants differ only after a deletion: **stale** leaves the summary note as it was (what a plain index does) and **rebuilt** regenerates it (a careful implementation). Showing both keeps the comparison from being a straw man.

## Questions

| Category | Count | Asked |
|---|---|---|
| Needs several sources | 10 | after the scheduled day |
| Timing and "last seen" | 8 | before and after the live wallet photo |
| Contradiction and correction | 6 | after the live photo |
| Should be refused | 6 | after the scheduled day |
| Must be forgotten | 6 | after Alex withdraws consent |
| Must still be answered | 4 | after Alex withdraws consent |

## Scoring

1. **Deterministic string checks decide the headline numbers**: an answer must contain the expected strings, a refusal question must be refused, a forgotten fact is a leak if a leak term appears.
2. **A model judge gives a second opinion.** For forgotten facts a leak is counted if the strings **or** the judge say so; otherwise the judge only flags disagreement.
3. **Every disagreement was read by a person** (`REVIEW.md`) and the decisions are recorded.

## Results (3 November 2026, mean of three runs)

| Measure | MemoryAtlas | Baseline, stale summary | Baseline, rebuilt summary |
|---|---|---|---|
| Questions handled correctly, strict (of 40) | **39.67** | 24 | 30 |
| Same, after hand review | **39.67** | 30 | 35.33 |
| Answerable questions correct (of 28) | 28 | 17.67 | 18 |
| Confident wrong answers (of 28) | 0 | 8.67 | 8.33 |
| Should-refuse questions answered (of 6) | 0 | 0 | 0 |
| Forgotten facts recoverable (of 6) | 0.33\* | 5.67 | 0 |
| Leak checks passed | 7 of 7 every run | n/a | n/a |
| Raw media retained | 0 bytes | 0 bytes | 0 bytes |
| Median answer time | 13.5 s | 9.1 s | 8.6 s |
| 95th percentile answer time | 32.3 s | 15.3 s | 14.8 s |
| Model calls per question | 3.75 | 1 | 1 |

\* One judge-only flag on "I have no record of what Alex promised." It is a false alarm, kept in the count; the true figure is 0.

## Reading it honestly

- **Where MemoryAtlas is ahead:** it does not leak forgotten facts (a baseline that keeps its summary repeats the conversation in 5.67 of 6 questions), it never gave a confident wrong answer, and it connects sources the baseline could not.
- **Where it is not:** a baseline that **rebuilds** its summary after a deletion matches it on forgetting *at the level of answers*. MemoryAtlas's advantage there is that forgetting is deterministic and verified, not that the answers differ. On timing and correction questions the two tie once clock times are not demanded.
- **It is slower**, because it makes about 3.75 dependent model calls per answer against 1. Latency was higher for both systems in this run than on 2 November, probably the model endpoint.
- **Two failures from the first run were fixed after being seen** (an over-broad "last confirmed sighting" check that rejected a before-or-after question, and a "this morning" read as the real date), moving MemoryAtlas from 38.67 to 39.67. That is a **re-test of a fix, not proof of generalising**.

## Limits

One small staged day with hand-written inputs; questions that overlap heavily in the facts they test; a baseline we designed; three runs show spread, not significance. A **held-out day** is drafted to test generalisation (see [Roadmap](Roadmap)).

## Reproduce

```bash
export MODEL_API_KEY=...        # never commit it
cd backend && . .venv/bin/activate
python scripts/run_eval.py --label my-run --runs 3
```

A run takes about an hour of live model time. `--only M01,T01` runs a few questions; `--aggregate-only` rebuilds the tables.

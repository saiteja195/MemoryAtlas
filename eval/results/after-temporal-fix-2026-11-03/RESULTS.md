# Evaluation results — after-temporal-fix-2026-11-03

Model `muse-spark-1.3` · 3 run(s) · 40 questions · commit `5110c53` · 2026-11-03

Values are the mean over runs; the range is the lowest–highest run.

## Strict scoring (fixed before the run)

An answer counts only if it contains the expected strings, including clock times such as `17:45`.

| Measure | MemoryAtlas | Baseline (stale summary) | Baseline (rebuilt summary) |
|---|---|---|---|
| All 40 questions handled correctly (correct answer, correct refusal, or no leak) | 39.67/40 (range 39–40) | 24/40 (range 23–26) | 30/40 (range 29–32) |
|   new questions, not used during development | 21/21 | 15.33/21 (range 14–16) | 17/21 (range 16–18) |
|   questions that were also demo-act questions during development | 18.67/19 (range 18–19) | 8.67/19 (range 7–10) | 13/19 (range 11–15) |
| All answerable questions correct | 28/28 | 17.67/28 (range 17–19) | 18/28 (range 17–20) |
| Multi-source questions answered correctly | 10/10 | 9/10 (range 8–10) | 9/10 (range 8–10) |
| Timing and last-seen questions correct | 8/8 | 4.67/8 (range 4–5) | 4.67/8 (range 4–5) |
| Contradiction / correction questions correct | 6/6 | 1/6 (range 0–2) | 1/6 (range 0–2) |
| Questions that should be refused, correctly refused | 6/6 | 6/6 | 6/6 |
| Confident answers with no support (should-refuse questions answered) | 0/6 | 0/6 | 0/6 |
| Confident but wrong answers (answerable questions) | 0/28 | 8.67/28 (range 8–10) | 8.33/28 (range 7–10) |
| Forgotten facts still recoverable from answers (lower is better) | 0.33/6 (range 0–1) | 5.67/6 (range 5–6) | 0/6 |
|   of which found by the string check | 0/6 | 5.67/6 (range 5–6) | 0/6 |
| Facts wrongly lost (kept questions not answered) | 0/4 | 1/4 | 0.67/4 (range 0–1) |
| Model errors | 0/40 | 0/40 | 0/40 |
| Recall latency, median seconds | 13.52 (range 11.1–17.93) | 9.14 (range 7.68–10.61) | 8.64 (range 7.33–9.78) |
| Recall latency, 95th percentile seconds | 32.27 (range 27.88–35.73) | 15.29 (range 11.69–20.17) | 14.79 (range 11.04–20.17) |
| Model calls per question | 3.75 (range 3.65–3.88) | 1 | 1 |

## After reading every row where the judge and the strings disagreed

All disagreeing rows were read by hand (see `README.md` in this folder). Where the judge said correct and the strings said wrong, the answer was right but omitted a clock time; those now count. Leaks are not adjusted: a leak is counted if the strings or the judge found one, so a judge-only flag stays in the count even when the README says it was a false alarm (conservative).

| Measure | MemoryAtlas | Baseline (stale summary) | Baseline (rebuilt summary) |
|---|---|---|---|
| All 40 questions handled correctly (correct answer, correct refusal, or no leak) | 39.67/40 (range 39–40) | 30/40 (range 29–32) | 35.33/40 (range 34–37) |
|   new questions, not used during development | 21/21 | 18.33/21 (range 17–19) | 20/21 (range 19–21) |
|   questions that were also demo-act questions during development | 18.67/19 (range 18–19) | 11.67/19 (range 10–13) | 15.33/19 (range 14–17) |
| All answerable questions correct | 28/28 | 23.67/28 (range 23–25) | 23.33/28 (range 22–25) |
| Multi-source questions answered correctly | 10/10 | 9/10 (range 8–10) | 9/10 (range 8–10) |
| Timing and last-seen questions correct | 8/8 | 5.67/8 (range 5–6) | 5.67/8 (range 5–6) |
| Contradiction / correction questions correct | 6/6 | 5/6 (range 4–6) | 5/6 (range 4–6) |
| Questions that should be refused, correctly refused | 6/6 | 6/6 | 6/6 |
| Confident but wrong answers (answerable questions) | 0/28 | 2.67/28 (range 2–4) | 3/28 (range 2–5) |
| Facts wrongly lost (kept questions not answered) | 0/4 | 0/4 | 0.33/4 (range 0–1) |

- Raw media retained after processing: **0 bytes** (MemoryAtlas); the baseline indexes the same text observations, so it keeps none either.
- MemoryAtlas leak probes passed per run: 7/7, 7/7, 7/7.
- Revocation took 113.32s, 122.559s, 134.456s (includes the red-team probe's live model calls).
- Baseline stores after Alex's withdrawal (leak terms still present):
  - run 1, baseline_stale: in chunks none; in the summary note ['friday', 'pastor', 'proposal', 'taco place']
  - run 1, baseline_rebuilt: in chunks none; in the summary note none
  - run 2, baseline_stale: in chunks none; in the summary note ['friday', 'pastor', 'proposal', 'taco place']
  - run 2, baseline_rebuilt: in chunks none; in the summary note none
  - run 3, baseline_stale: in chunks none; in the summary note ['friday', 'pastor', 'proposal', 'taco place']
  - run 3, baseline_rebuilt: in chunks none; in the summary note none

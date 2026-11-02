# Evaluation results — full-2026-11-02

Model `muse-spark-1.3` · 3 run(s) · 40 questions · commit `605aba9` · 2026-11-02

Values are the mean over runs; the range is the lowest–highest run.

## Strict scoring (fixed before the run)

An answer counts only if it contains the expected strings, including clock times such as `17:45`.

| Measure | MemoryAtlas | Baseline (stale summary) | Baseline (rebuilt summary) |
|---|---|---|---|
| All 40 questions handled correctly (correct answer, correct refusal, or no leak) | 38.67/40 (range 38–39) | 24.67/40 (range 23–27) | 29.67/40 (range 29–31) |
|   new questions, not used during development | 19.67/21 (range 19–20) | 15.67/21 (range 15–17) | 17.33/21 (range 17–18) |
|   questions that were also demo-act questions during development | 19/19 | 9/19 (range 8–10) | 12.33/19 (range 12–13) |
| All answerable questions correct | 26.67/28 (range 26–27) | 17.67/28 (range 17–19) | 17.67/28 (range 17–19) |
| Multi-source questions answered correctly | 10/10 | 8.33/10 (range 8–9) | 8.33/10 (range 8–9) |
| Timing and last-seen questions correct | 7/8 | 5/8 | 5/8 |
| Contradiction / correction questions correct | 5.67/6 (range 5–6) | 1.33/6 (range 1–2) | 1.33/6 (range 1–2) |
| Questions that should be refused, correctly refused | 6/6 | 6/6 | 6/6 |
| Confident answers with no support (should-refuse questions answered) | 0/6 | 0/6 | 0/6 |
| Confident but wrong answers (answerable questions) | 0/28 | 8.33/28 (range 7–9) | 8.33/28 (range 7–9) |
| Forgotten facts still recoverable from answers (lower is better) | 0/6 | 5/6 (range 4–6) | 0/6 |
|   of which found by the string check | 0/6 | 4.33/6 (range 3–6) | 0/6 |
| Facts wrongly lost (kept questions not answered) | 0/4 | 1/4 | 1/4 |
| Model errors | 0/40 | 0/40 | 0/40 |
| Recall latency, median seconds | 6.93 (range 6.67–7.11) | 4 (range 3.85–4.11) | 3.98 (range 3.92–4.04) |
| Recall latency, 95th percentile seconds | 16.62 (range 15.17–18.24) | 8.26 (range 7.35–9.08) | 6.44 (range 6.01–7.17) |
| Model calls per question | 3.78 (range 3.75–3.8) | 1 | 1 |

## After reading every row where the judge and the strings disagreed

All disagreeing rows were read by hand (see `README.md` in this folder). Where the judge said correct and the strings said wrong, the answer was right but omitted a clock time; those now count. Leaks need no adjustment: they are already counted if the strings or the judge found one, and each judge-only leak was confirmed.

| Measure | MemoryAtlas | Baseline (stale summary) | Baseline (rebuilt summary) |
|---|---|---|---|
| All 40 questions handled correctly (correct answer, correct refusal, or no leak) | 38.67/40 (range 38–39) | 31.33/40 (range 30–33) | 36.33/40 (range 36–37) |
|   new questions, not used during development | 19.67/21 (range 19–20) | 19.33/21 (range 19–20) | 21/21 |
|   questions that were also demo-act questions during development | 19/19 | 12/19 (range 11–13) | 15.33/19 (range 15–16) |
| All answerable questions correct | 26.67/28 (range 26–27) | 24.33/28 (range 24–25) | 24.33/28 (range 24–25) |
| Multi-source questions answered correctly | 10/10 | 8.33/10 (range 8–9) | 8.33/10 (range 8–9) |
| Timing and last-seen questions correct | 7/8 | 6/8 | 6/8 |
| Contradiction / correction questions correct | 5.67/6 (range 5–6) | 6/6 | 6/6 |
| Questions that should be refused, correctly refused | 6/6 | 6/6 | 6/6 |
| Confident but wrong answers (answerable questions) | 0/28 | 1.67/28 (range 1–2) | 1.67/28 (range 1–2) |
| Facts wrongly lost (kept questions not answered) | 0/4 | 0/4 | 0/4 |

- Raw media retained after processing: **0 bytes** (MemoryAtlas); the baseline indexes the same text observations, so it keeps none either.
- MemoryAtlas leak probes passed per run: 7/7, 7/7, 7/7.
- Revocation took 56.876s, 55.467s, 66.825s (includes the red-team probe's live model calls).
- Baseline stores after Alex's withdrawal (leak terms still present):
  - run 1, baseline_stale: in chunks none; in the summary note ['friday', 'pastor', 'proposal', 'taco place']
  - run 1, baseline_rebuilt: in chunks none; in the summary note none
  - run 2, baseline_stale: in chunks none; in the summary note ['friday', 'pastor', 'proposal', 'taco place']
  - run 2, baseline_rebuilt: in chunks none; in the summary note none
  - run 3, baseline_stale: in chunks none; in the summary note ['friday', 'proposal', 'taco place']
  - run 3, baseline_rebuilt: in chunks none; in the summary note none

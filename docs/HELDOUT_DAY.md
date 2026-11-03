# The held-out day (issue #12)

A second staged day, written after the system was built against the first, to test whether the results
in `docs/EVALUATION.md` hold on facts the system was never tuned on. **Status: draft for review, not yet
run.** Nothing here has been run against the system or the baseline.

Files: `fixtures/heldout_day/script.yaml` (the day), `eval/heldout_questions.yaml` (40 questions, same
categories and scoring as the first set).

## The day

Thursday 30 October 2026, fictional. Three people, three sessions, eleven events.

| Time | Event | Source |
|---|---|---|
| 07:50 | Keys with a red tag on the kitchen counter at home | photo |
| 08:20 | Station display: Harbor Line, platform 3, delayed 15 min | photo |
| 09:05 | Navy umbrella on a chair and a black laptop bag, Kestrel Coffee | photo |
| 10:00 | Roadmap review with Priya, Room 4B, Pier 9 Offices | calendar |
| 10:05 | Priya: try the yellow-door bakery (best sourdough); budget draft by Thursday; loading dock code 4417 | conversation (me + Priya) |
| 12:30 | Lunch with Sam, Fig Street Market | calendar |
| 12:40 | Sam: try the harbor bakery with the striped awning (cinnamon buns); moving to Denver in March; photos on Saturday | conversation (me + Sam) |
| 13:25 | Marrow & Rye Bakery, yellow door | photo |
| 13:40 | Tidewater Bakery, red and white striped awning | photo |
| 15:10 | Whiteboard in Room 4B: Q1 launch Feb 12, Beta Jan 8 | photo |
| 17:20 | Navy umbrella on the office coat stand (uploaded live, no GPS) | photo |

Priya withdraws consent after the live photo. Sam does not.

## What it tests that the first day did not

| Stressor | Where | Why it matters |
|---|---|---|
| **Two similar sources, only one revoked** | Priya vs Sam, both recommend a bakery | The first day had one conversation. Forgetting must remove Priya's recommendation and keep Sam's (K03, K04), not just "the conversation". |
| **Two similar candidates** | Marrow & Rye vs Tidewater | Resolving "yellow door" vs "striped awning" needs the photo, not luck. |
| **Link through a role, not a name** | M06 "the person I had lunch with", M07 "the person from my 10am review" | The system must go calendar → attendee → conversation → recommendation. |
| **Link through a place** | M08 whiteboard in "the room where I met Priya" | Needs the calendar location matched to a photo's place name. |
| **A secret detail only the revoked source holds** | the dock code 4417 | A cleaner leak test than a recommendation: one unambiguous token. |
| **Several things "left" at once** | keys (never moved), umbrella (moved once), laptop bag (never moved) | Last-seen phrasing must apply to each object, and a moved object must not be reported at its old place. |
| **Ordering phrasing the code was not tuned on** | T08 uses "following", which is not in the ordering-word list | A direct probe of the fix made after the first evaluation. |
| **Questions the day cannot answer but sounds like it can** | R01–R06 | A budget draft was promised but no figure exists; a photo of a bakery is not a purchase. |

## Rules

1. **Freeze.** The commit that adds the questions and script to `main` is the freeze. No question,
   expected string, rubric or fixture event changes after that because of how a system scores. A badly
   written question stays in, is reported as badly written, and any replacement is a separate set.
2. **No tuning.** No prompt, tool, post-check, retrieval parameter or baseline prompt changes in response to
   results on this day. If the run exposes a defect, it is reported as a result and fixed in a separate
   change after the numbers are published.
3. **Allowed before the run:** only what is needed to run it: letting the evaluation runner load a different
   day (it is currently hard-wired to the first day's events and to Alex), and one live pass to record the
   model responses ingestion needs (extraction, vision, claim compilation). Those recordings are made once and
   not redone to get better claims.
4. **Run once, publish regardless.** Three live runs as before, same model, same two baselines, same
   strict and judge scoring, hand review of every disagreement. Results go in
   `eval/results/heldout-<date>/` whatever they show, including a failing result.
5. **No peeking.** I will not run any of these questions against the system before the real run.

## Predictions, written before the run

So that the result can be read against something other than hindsight. I think these are the most likely
failures, in order of confidence:

- **H-T08** ("following"): may abstain if the ordering check does not recognise the word.
- **H-M06 / H-M07** (role-based links): may need more search steps than the investigator's budget.
- **H-M08** (whiteboard by room): depends on matching "Room 4B" between the calendar and the photo's place.
- **H-F02** (leak): the storefront photo of Marrow & Rye survives, so an answer may mention the bakery
  without the recommendation. The strict check only looks for "sourdough"; the judge decides the rest.
- The retrieval baseline will probably do better than on the first day on multi-source questions, because
  more of the day fits in its top 8 than the new volume would suggest (about 12 observations).

If none of these fail, the likely reading is that the day is still too small, not that the system is
robust. The volume is deliberately modest so the day can be reviewed by hand; a larger synthetic day
(hundreds of observations) is the storage-scale spike (#29), not this.

## What running it needs

- A `--day` option in `backend/scripts/run_eval.py` and the runner (script path, question path, which live
  event to play, which person withdraws). About a small change, covered by offline tests with the
  scripted stand-in model.
- One recording pass of ingestion with the live key, committed to `fixtures/llm_cache`.
- About an hour of live model time for three runs.

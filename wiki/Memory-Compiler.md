# Memory Compiler

`backend/app/compiler/` turns one observation into claims. Deterministic steps are marked ⚙, model steps ✦.

| # | Step | Module | |
|---|---|---|---|
| 1 | **Perceive** a photo into caption, visible text, objects with attributes, scene | `perceive.py` | ✦ Muse Spark vision |
| 2 | **Episode binding**: group observations by time and place into `episode` entities, remembering which sources contributed the time and place | `episodes.py` | ⚙ |
| 3 | **Extract claims** with a controlled vocabulary. The JSON schema is enforced by Pydantic; an unusable reply is repaired once, then rejected and logged | `extract.py` | ✦ Muse Spark |
| 4 | **Resolve entities**: exact or alias match first; for ambiguous cases the model picks between the top candidates and the decision is recorded as a `same_as` claim | `resolve.py` | ⚙✦ |
| 5 | **Derive**: a few named rules. The model proposes a binding and code validates it | `derive.py` | ✦⚙ |
| 6 | **Contradiction pass**: two claims placing the same object in different places over overlapping times are both marked `disputed`, so answers must surface the conflict | `contradiction.py` | ⚙ |
| 7 | **Write** claims, justifications, the FTS row and the vector | `store.py`, `pipeline.py` | ⚙ |
| – | **To-do scan**: finds promises and requests ("I'll send you the proposal by Friday") | `todo_scan.py` | ✦ |

## Derivation rules

- **`spatial_referent_resolution`**: "the taco place across the street" + the meeting location + a photo of a taco shop with matching attributes nearby → `recommended(alex, luna_taqueria)`. Its premises are the transcript claim, the location claim and the sign claim. This is the cross-source reconstruction behind the headline demo question.
- **`last_seen`**: the latest sighting per object by **event time**, not ingest order.
- **`episode_summary`**: a one-paragraph summary whose premises are the claims it uses, so it disappears if one of them does.

## Why justifications matter

Every claim records *why it holds*: the source it was read from, or the premises it was derived from. That record is what makes forgetting exact. See [Data Model](Data-Model) and [Forgetting and Consent](Forgetting-and-Consent).

## Confidence

A heuristic, stated plainly: direct observations use the model's confidence scaled down; user confirmations are near-certain; inferences are capped by their weakest premise. It is not calibrated, and the evaluation does not claim it is.

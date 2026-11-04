# Demo Day Script: "A Day You Forgot"

A staged, fictional day (29 October 2026) used for the demo, the tests and the evaluation. The fixture is `fixtures/demo_day/script.yaml`; names and businesses are fictional and the inputs are hand-written placeholders for what the vision and speech steps would return.

## The day

| Time | Event | Source |
|---|---|---|
| 09:10 | A brown wallet on a café table, Blue Door Café | photo |
| 09:40 | A billboard: "Orbit Fitness: first month free" | photo |
| 12:30 | Sync with Alex, Office, 400 Market St | calendar |
| 12:35 | Alex: "You've got to try the taco place right across the street from your office, the one with the green awning. Best al pastor." Later: "I'll send you the proposal by Friday." | conversation (me + Alex) |
| 13:20 | A taco storefront with a green awning: "Luna Taqueria" | photo |
| 17:45 | The wallet in a car's cup holder (uploaded live, no GPS) | photo |

Alex's conversation depends on **both** people's consent.

## The acts (about three minutes)

| Act | Action | What the audience sees |
|---|---|---|
| **Remember** | Play the day | The graph builds itself, colour-coded by source. Raw media kept: **0 bytes** |
| **Connect** | Ask "Which restaurant did Alex recommend when we met near the office?" | *Luna Taqueria*. **Why?** shows a three-source path: conversation, meeting location, sign |
| **Correct** | Ask "Did I leave my wallet at the café?" Then upload the 17:45 photo and ask again | First: "Last confirmed sighting at 09:10 at Blue Door Café." Then the answer moves to the car; the café sighting is greyed but kept as history |
| **Forget** | Alex withdraws consent. Ask "What did Alex promise me?" and "Which restaurant did Alex recommend?" | The conversation's facts disappear and the answers become "no record". "I met Alex at 12:30" (calendar) and Luna Taqueria's green awning (photo) **survive**. The receipt shows 7 of 7 checks |
| **Proof** | Show the [Evaluation](Evaluation) | Numbers against a retrieval baseline |

*"We didn't delete a recording. Alex withdrew consent, and every memory that depended only on that consent is gone, provably."*

## Run it yourself

- In the app, press **Play the day**, then **Upload live photo · 17:45**.
- From the command line, `backend/scripts/ask_demo.py`, `correct_demo.py` and `revoke_demo.py` replay the acts against recorded responses (or record new ones with a key).
- `fixtures/demo_day/acts.yaml` holds the demo questions and what each answer must or must not contain.
- A second, **held-out** day is drafted to test whether results hold on facts the system was never developed against (see [Roadmap](Roadmap)).

# Meta Models

MemoryAtlas uses three models from the Meta Model API. All calls go through one client (`backend/app/llm/meta.py`).

| Model | Used for | Where |
|---|---|---|
| **Muse Spark 1.3** (`muse-spark-1.3`) | Reads photos and video frames into captions, visible text and objects. Extracts structured claims. Adjudicates whether two entities are the same. Writes episode summaries and finds to-dos. Runs the recall investigator. Answers the adversarial questions in the forgetting check | `compiler/perceive.py`, `extract.py`, `resolve.py`, `derive.py`, `todo_scan.py`, `recall/investigator.py` |
| **Muse Voice Transcribe 1.0** (`muse-voice-transcribe-1.0`) | Diarized, timestamped transcription, so each line is attributed to a speaker and can be tied to that person's consent | `llm/meta.py` (`POST /v1/asr/transcribe`, DIARIZATION mode), `capture/gateway.py` |
| **SAM 3.1** (`sam-3.1`) | Optional: finds a named object in sampled video frames. Only time ranges are kept, never boxes or masks. People are never tracked | `tracking.py`, `llm/meta.py` (`detect_objects`) |

## API shapes in use

- `POST https://api.meta.ai/v1/responses` with `input_text` and `input_image` parts and a `system` message, for text and vision.
- `POST /v1/asr/transcribe`, multipart `request` and `audio` (WAV, mono, 16-bit PCM, 16 or 24 kHz, up to 10 minutes, DIARIZATION).
- Bearer auth with `MODEL_API_KEY`. Retries on 429 and 5xx with backoff. Shapes were checked against the live API on 2 November 2026 with `scripts/smoke_meta.py`.
- **Structured output** is requested in the prompt and validated with Pydantic. Native structured-output parameters are untried.
- **Not Meta:** the model list has no embedding model, so vectors are computed locally (feature-hashed character 3-grams in exact integer arithmetic).

## Record and replay

`RecordReplayClient` caches each response by a hash of the request. That gives:

- an **offline app** and demo that need no key (`replay` mode);
- a test suite that runs against recorded or scripted responses;
- reproducibility, which is why vector ranking uses integer arithmetic: another CPU must rank identically or the request hash changes and the recording no longer matches.

The committed `fixtures/llm_cache/` is read-only seed data. At run time responses are written to a separate runtime cache, which a forgetting purge cleans.

## Metering

`MeteredLLM` writes one `model_calls` row per call: when, which model, kind (text, vision, asr), purpose, timings and sizes. **Never prompts, replies, transcripts or media.** The dashboard shows these counts.

## Model usage per feature

- Adding a photo: one vision read plus a few extraction calls.
- Several photos or a video: one read per photo or frame (in parallel), then a few extraction calls for the merged memory.
- A recall question: about 3.75 dependent Muse Spark calls on average in the evaluation.
- Revocation: the red-team check makes live calls; it took 113 to 134 seconds in the evaluation runs.

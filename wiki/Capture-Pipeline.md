# Capture Pipeline

Everything that enters MemoryAtlas passes the **capture gateway** (`backend/app/capture/gateway.py`). Its order of operations is fixed:

1. **Consent check.** Audio is accepted only if an active grant covers the session for **every** participant. Photos, notes and calendar entries carry the owner's own grant.
2. **Perceive or transcribe.** A photo goes to Muse Spark vision; audio goes to Muse Voice Transcribe with speaker diarization.
3. **Local redaction.** Card numbers (Luhn-checked), emails and phone numbers in the derived text are replaced before anything is stored or forwarded again. Counts are kept, never values.
4. **Hash** the text, then **check `blocked_hashes`**: content that was forgotten cannot be re-ingested by replaying it.
5. **Insert a text-only source row** and record every grant the source depends on.
6. **Drop the raw bytes.** `media_bytes_retained` is constrained to 0 in the schema.

## Ways in

| Way | What it does |
|---|---|
| Scripted day | `MockDayAdapter` replays `fixtures/demo_day/script.yaml` (the demo path) |
| Upload in the app | Photo(s), voice, video or a typed note, with a review step before saving |
| Capture in the browser | Take a photo or record voice or video with the device camera and microphone |
| Live photo (demo) | Plays the late wallet photo to show self-correction |

## The upload flow

Adding your own memory is two steps so that nothing is stored until the person is happy with what Muse understood.

1. **Preview** (`POST /capture/preview`). Muse reads the file and the response is a **draft**: *When*, *Where*, *Doing*, *Seen*, *People*, each marked **Sure**, **Check** or **Ask**, plus the questions still open. Which questions are asked is decided by code in `capture/draft.py`, not by the model. The draft lives in memory for 15 minutes and holds text only.
2. **Commit** (`POST /capture/commit/start`). The answers are validated: when it happened, the place, which speaker is the owner, and for **each other person** whether they agreed. A "no" means nothing is stored and no grant is created. A "yes" creates that person's own grant and shows their withdrawal code **once**.

### What can be added

| Input | Limits | How it is read |
|---|---|---|
| **Photos** | 1 to 8 at once (60 MB together), JPEG or PNG, 10 MB each | One Muse read per photo, in parallel. Saved as **one memory**: *Seen* lists objects from every photo, *When* is the earliest photo time, visible people add up (at most three questions) |
| **Voice** | WAV, mono, 16-bit, 16 or 24 kHz, 10 minutes; the browser converts | Diarized transcription; speakers are mapped to people the owner names |
| **Video** | Up to 8 frames plus the audio track; 200 MB file | Frames read in parallel and merged into one memory (a long object list is saved in parts); audio transcribed |
| **Note** | 5,000 characters | Stored as a `user_confirmation` source |
| **Video object tracking** (opt-in) | Up to 12 frames, up to 3 named objects, never people | SAM 3.1 looks for each object per frame; only the **time ranges** it was visible are kept, as text |

A photo's time comes from its own metadata when it has any, otherwise from the file date (marked **Check**). A GPS fix is used when present.

## Consent and people

- Visible people are detected from the Muse description with a deliberately generous word list: asking about one too many costs a click, while missing one stores someone who never agreed.
- A recorded conversation depends on the grant of every participant, so any one of them withdrawing removes the recording.
- Consent can **expire**. A lapsed grant is refused immediately and purged by the same engine as a withdrawal.

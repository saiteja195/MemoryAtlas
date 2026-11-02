# Hackathon facts (verified)

Fill each row from the primary source and note the date. Anything marked **unverified** came from the
original pitch research and was not checked, because the event and Meta docs sites were unreachable from
the planning environment. Later decisions cite this file.

| # | Item | Value | Source | Status |
|---|---|---|---|---|
| 1 | Submission | Via the Cerebral Valley platform. **3-minute demo video** (primary judging artifact), **public repo**, everyone who worked on it listed. One project per team. Late submissions are not considered | Participant Guide §7 | verified |
| 2 | Meta model required? | Yes. Stage 1 is pass/fail: fits the theme and reasonably uses Meta Model API and/or Meta open-weight models | Guide §1, §8 | verified |
| 3 | Models | `muse-spark-1.3` (recommended): text, image, video, audio, PDF in; text out; 1,048,576-token context; chat, image understanding, tool calling, structured output, search grounding. Its audio support is degraded, so use `muse-voice-transcribe-1.0` for speech. `muse-spark-1.3-contributor` variant exists. Also Muse Wonder, Muse Image, SAM 3.1, and open-weight Muse Spark Open / Muse Glimmer (no API) | Model docs (screenshots, Nov 2) | verified |
| 4 | API shape | `POST https://api.meta.ai/v1/responses` (also Chat Completions and Messages endpoints), `Authorization: Bearer $MODEL_API_KEY`, content parts `input_text`. Voice: `POST /v1/asr/transcribe`, multipart `request` (JSON) + `audio` (WAV, mono 16-bit PCM, 16 or 24 kHz, max 10 min, max 32 MB), modes PUSH_TO_TALK / ENDPOINTING / DIARIZATION, speaker labels A/B are session-scoped, turn-level timestamps only, `keywords` biasing. No embedding model is listed | Docs + quickstart (Nov 2) | verified; live smoke test on Nov 2 confirmed the `system` message shape, the `input_image` part (base64 data URL) and DIARIZATION transcription; native structured-output params still **untried** (the client asks for JSON in the prompt) |
| 5 | Credits and limits | $150 Meta Model API credit per participant, claimed individually via the form by **Wed Nov 4, 9 PM ET**; a credit card on file is required. Voice: 256 concurrent streams, 16,000 streams/hour. Pricing: Spark 1.3 $1.25 in / $0.15 cached / $4.25 out per M tokens; Voice $0.18 per audio hour | Guide §5, docs | verified (Spark rate limits unknown) |
| 6 | Data retention | The Voice docs mention **zero data retention (ZDR)** at price parity with Standard mode. How to enable it, and whether Spark supports it, is unknown. The contributor model variant relates to data sharing | Voice docs | **open**: check the dashboard before making any provider-side privacy claim |
| 7 | Wearables toolkit | Not mentioned in the Participant Guide. Treat glasses support as optional | Guide | not required |
| 8 | Team and code rules | Max 4 per team, solo allowed. **Must be built during the event (Oct 27 to Nov 4)**; the demo must show only what was built then. Repos must be public. No rights-violating code, data or assets | Guide §4 | verified |
| 9 | Deadline | **Wed Nov 4, 9:00 PM ET.** Last full day for submission questions: Tue Nov 3. Discord office hours weekdays 10 to 11 AM ET | Guide §3 | verified |
| 10 | Judging rubric | Impact 30%, Use of Meta AI tooling 25%, Demo 25%, Technical depth and execution 20%. Top 5 per track reach the live final round | Guide §8 | verified |
| 11 | Anti-projects (avoid looking like these) | Basic RAG apps, simple image analyzers, anything giving medical advice, anything political or war-related, plus several generic "AI coach" ideas | Guide §4 | verified |
| 12 | Prizes | Indie track: $150K / $100K / $75K / $50K / $25K. Bonus: Best Agentic Use-Case $5K | Guide §9 | verified |

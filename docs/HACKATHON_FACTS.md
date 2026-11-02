# Hackathon facts (verified)

Fill each row from the primary source and note the date. Anything marked **unverified** came from the
original pitch research and was not checked, because the event and Meta docs sites were unreachable from
the planning environment. Later decisions cite this file.

| # | Item | Value | Source | Status |
|---|---|---|---|---|
| 1 | Submission requirements (video length, repo, form fields) | | | unverified |
| 2 | Must a Meta model/API be used? | | | unverified |
| 3 | Model ids and capabilities | `muse-spark-1.3` (recommended for new work; also `-1.2`, `-1.1`): input text, image, video, audio, PDF; text output; 1,048,576-token context; chat completion, image understanding, tool calling, structured output, search grounding. Audio on 1.3 is not fully supported, so use Muse Voice Transcribe (or 1.2) for speech. `muse-spark-1.3-contributor` variant exists (no `max` reasoning). `muse-wonder-1.0` is used in the docs for long-running agent work. Muse Spark Open is an open-weight download (not used). | Meta model docs, Muse Spark section (screenshot, Nov 2) | verified |
| 4 | API shape (OpenAI-compatible? base URL, SDK) | | | unverified |
| 5 | Rate limits and credits | | | unverified |
| 6 | Data retention / Contributor settings | | | unverified |
| 7 | Wearables toolkit: Mock Device Kit, platforms | | | unverified |
| 8 | Team size and pre-existing code rules | | | unverified |
| 9 | Deadline | Wed Nov 4, 2026, 9 PM ET | pitch research | unverified |

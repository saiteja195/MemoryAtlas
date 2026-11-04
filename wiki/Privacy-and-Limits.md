# Privacy and Limits

## What MemoryAtlas guarantees

- **No raw media is kept.** A photo, audio or video is turned into text and the bytes are dropped. `media_bytes_retained` is constrained to 0, a disk check scans for media files, and the app displays **Raw media kept: 0 B**.
- **Consent is enforced by code.** A source is stored only if everyone in it agreed, a recorded conversation depends on every participant, and a "no" during upload stores nothing.
- **Forgetting is complete for what MemoryAtlas stores**: claims, search index, vectors, caches, the model-response cache, the chat log, exports, episode metadata and receipts, verified by seven checks, including a scan of the database file.
- **Receipts and logs hold no content.** Receipts store counts and results; the model-call log stores counts and sizes, never prompts, replies, transcripts or media.
- **Each profile is private.** Separate database per profile; sign-in with a name and passcode.
- **Demo snapshots are text only**, with no photo, audio, video or GPS position.

## What it does not guarantee

- **Meta's side.** Raw audio and images are sent to Meta's speech and vision endpoints to be turned into text, and the text goes to Muse Spark. That is covered by Meta's terms, not by these checks. Local redaction only limits what is stored or forwarded again from the derived text. Whether zero data retention can be enabled for these models is an open question for the provider.
- **Redaction is pattern based.** It catches card numbers (Luhn-checked), emails and phone numbers; it does not understand every kind of identifier.
- **Withdrawal codes are shown once.** Keep them. The server stores only a hash.
- **No passcode reset.** There is no email; a forgotten passcode means a new profile.
- **The consent page is a simulation.** Withdrawing as another person uses a second browser tab, not a real identity check.
- **Model reading can be wrong.** Muse may misread a photo or miss text. The review step shows what it found, marked Sure, Check or Ask, so a person can correct it before saving.
- **Confidence scores are heuristic**, not calibrated.
- **One small staged day** underlies the evaluation. See [Evaluation](Evaluation).

## Defence in depth

Revocation purges the stores, and the privacy filter still refuses any claim whose support is gone, so a missed purge would not become a leak through recall. Questions are stateless, so conversation history cannot carry a forgotten fact. Content that was forgotten is blocked by hash from being ingested again.

## Reporting a problem

Open an issue on <https://github.com/saiteja195/MemoryAtlas/issues>. Please do not include real personal content in an issue.

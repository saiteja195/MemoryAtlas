# Glossary

| Term | Meaning |
|---|---|
| **Atlas** | The browser app and the memory graph it shows |
| **Claim** | One structured fact: subject, predicate, object or value, time, evidence type, confidence |
| **Justification** | A recorded reason a claim holds: a source, or a set of premise claims |
| **Premise** | A claim a derivation depends on. A derivation holds only if **all** its premises are supported |
| **Support** | A claim is supported if **some** justification holds. The **least fixpoint** of these rules, built from live sources, so cycles cannot keep each other alive |
| **Source** | One stored observation: derived text plus a content hash and time. Never raw media |
| **Grant** | A record that a person agreed to something, with a withdrawal code shown once |
| **Revoke / withdraw** | End a grant. Everything resting only on it is deleted |
| **Expire** | A grant past its expiry counts as withdrawn and the same purge runs |
| **Episode** | A group of observations close in time and place |
| **Supersede** | Replace a claim with newer evidence or a correction while keeping the old one as history |
| **Disputed** | Two claims conflict (for example an object in two places at once); answers must say so |
| **Draft** | What Muse understood from an upload, with open questions. Held in memory until you save |
| **Investigator** | The bounded tool-using loop that answers questions from the graph |
| **Post-check** | A deterministic code check on an answer: citations exist, last-seen wording, disputes, numbers |
| **Last confirmed sighting** | The required phrasing for "where is X": a sighting does not prove where something is now |
| **Leak probe** | One of seven automated checks that forgotten content is gone |
| **Receipt** | The proof of a forgetting: counts and check results, no claim text |
| **Privacy filter** | The deterministic gate every read goes through; refuses revoked, superseded or unauthorised claims |
| **Blocked hash** | The hash of forgotten content, so it cannot be ingested again |
| **Record / replay** | Caching model responses by request hash so the app and tests run offline |
| **Muse Spark** | Meta's text and vision model used for reading, extraction and answering |
| **Muse Voice Transcribe** | Meta's speech model, with speaker diarization |
| **SAM 3.1** | Meta's segmentation model, used for opt-in object tracking in video |
| **Held-out day** | A second staged day built to test that nothing is tuned to the first |

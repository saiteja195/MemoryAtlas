# Demo profile snapshots

Two demo profiles are published in the README so reviewers can try MemoryAtlas without signing up:

| Profile  | Built from                                              | Snapshot                    |
|----------|---------------------------------------------------------|-----------------------------|
| `staged` | the scripted day in `fixtures/demo_day/script.yaml`     | `fixtures/profiles/staged.db` |
| `real`   | the owner's own photos, voice notes and text notes      | `fixtures/profiles/real.db`   |

A snapshot is a **text-only** SQLite file: claims, sources as text, grants and receipts. It never holds a photo,
audio, video or GPS position. A demo profile starts from its snapshot the first time someone signs in, and the
visitor can press Reset to put it back.

## Build them

```bash
cd backend
export MODEL_API_KEY=...                         # never paste it into chat or commit it
export DEMO_STAGED_NAME="..." DEMO_STAGED_PASSCODE="..."
export DEMO_REAL_NAME="..."   DEMO_REAL_PASSCODE="..."

python scripts/seed_profiles.py staged --data-dir /tmp/seed-staged
python scripts/seed_profiles.py real   --data-dir /tmp/seed-real --media ~/demo-photos
```

Use a fresh, empty `--data-dir` each time. The script prints every stored claim.

## Checklist before committing `real.db`

Do this yourself; the script cannot know.

- [ ] Nobody appears in a photo or voice note unless they agreed to be in a public demo. Record each person
      in `manifest.yaml` (`consented: true`) or skip the file.
- [ ] No home or work address, licence plate, document or screen with personal data is readable in any photo
      (Muse reads text in images, and that text becomes a claim).
- [ ] You read every `- ...` claim the script printed and none is something you would not publish.
- [ ] Dates are right. Set `captured_at` in the manifest for every file; a file's own date is not trusted.
- [ ] GPS is stripped automatically. If a place name is private, answer `where:` with something generic.

## The manifest (`<media dir>/manifest.yaml`)

One entry per file, no exceptions. See `real/manifest.example.yaml`. A file with no entry stops the script;
write `skip: true` to leave a file out on purpose.

## Put them on the server

Create the two profile rows on the server (no Muse call, no content), using the same names and passcodes:

```bash
docker compose exec -e DEMO_STAGED_NAME=... -e DEMO_STAGED_PASSCODE=... backend \
  python scripts/seed_profiles.py register staged --data-dir /data
```

Commit the snapshots, rebuild the backend image and sign in as the demo profile: its memories appear.

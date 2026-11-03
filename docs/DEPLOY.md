# Deploying on a VM with HTTPS

Phones only let a web page use the camera and microphone on a secure page (`https://`, or `localhost`).
To use MemoryAtlas from your phone, run it on a VM behind a name that has a certificate. This
describes the setup with a free [DuckDNS](https://www.duckdns.org) name; any domain that points at the
VM works the same way.

The default `compose.yaml` only listens on `127.0.0.1`, on purpose. The public setup below puts HTTPS in front
of it. The app protects its own data: everyone **signs up with a name and a passcode** and sees only their own
memories (each profile has its own database). There is no email and no passcode reset; a forgotten passcode
means a new profile. Keep `MEMORYATLAS_AUTH` at its default (`on`) on a public VM: `off` has no sign-in at all.

## What you need

- A VM with Docker and the compose plugin, and ports **80 and 443** open to the internet (firewall and
  cloud security group). Port 80 is used to obtain the certificate.
- A DuckDNS name (for example `mynotes.duckdns.org`) pointing at the VM's public IP.
- A Meta model key, so the app runs in live mode. Adding memories does not work in replay mode.

## Steps

1. Clone the repository on the VM and create `.env` from `.env.example`.

2. Fill in `.env`:

   ```bash
   MEMORYATLAS_LLM_MODE=live
   MODEL_API_KEY=...                 # your key
   MEMORYATLAS_SECRET=...            # a long random string; keys the revocation tokens
   PUBLIC_HOST=mynotes.duckdns.org
   ```

3. Start it:

   ```bash
   docker compose -f compose.yaml -f deploy/compose.public.yaml up -d --build
   ```

   The override file stops the web container publishing a port and adds Caddy, which gets a certificate
   for `PUBLIC_HOST` automatically.

4. Open `https://mynotes.duckdns.org` on your phone, create a profile, and press **Add memory**. Allow the
   camera and microphone when the browser asks.

## Demo profiles for reviewers

Two profiles can be published in the README so reviewers can look around without signing up: one built from the
scripted day and one from your own photos. **Their names and passcodes are public on purpose and they hold only
demo content**; a visitor can reset them. See `fixtures/profiles/README.md` for the checklist.

1. On your machine, build each snapshot with live Muse and review the claims it prints:
   `python scripts/seed_profiles.py staged --data-dir /tmp/seed-staged` (and `real ... --media DIR`).
   Commit `fixtures/profiles/staged.db` and `real.db`. They hold text only, never photos, audio or GPS.
2. On the VM, after `git pull` and a rebuild, create the two rows (use the names and passcodes you publish):

   ```bash
   docker compose exec -e DEMO_STAGED_NAME="..." -e DEMO_STAGED_PASSCODE="..." backend \
     python scripts/seed_profiles.py register staged --data-dir /data
   docker compose exec -e DEMO_REAL_NAME="..." -e DEMO_REAL_PASSCODE="..." backend \
     python scripts/seed_profiles.py register real --data-dir /data
   ```

   A demo profile loads its snapshot the first time someone signs in to it.

To go back to local-only: `docker compose down`, then `docker compose up -d`. Your data lives in the
`data` volume and is kept.

## Notes

- Caddy keeps its certificate in the `caddy_data` volume. Do not delete it on every deploy: certificate
  authorities rate-limit how often a name can be issued one.
- Uploads are limited to 100 MB per request by both Caddy and the web container.
- Sign-up is open to anyone who can reach the site, so it is rate limited: 5 sign-ups an hour and 20 sign-in
  attempts per 10 minutes per address, 5 wrong passcodes lock a profile for 15 minutes (not the demo profiles,
  whose passcodes are public), and there is a cap of 500 profiles. The limits use the first address in
  `X-Forwarded-For`, which Caddy sets to the visitor's address; do not publish the web container's port
  directly alongside this setup.
- Sessions are cookies (`HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS) that last 30 days.
- If you used the old single shared login, its data stays in the volume but is not shown to any profile: the
  profile system starts empty.
- Back up the `data` volume: it holds `profiles.db` (names, passcode hashes) and every profile's database.
- To try the proxy on a machine where ports 80 and 443 are taken, set `PUBLIC_HTTP_PORT` and
  `PUBLIC_HTTPS_PORT`. A real domain will not get a certificate on other ports.

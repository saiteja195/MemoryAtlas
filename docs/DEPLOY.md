# Deploying on a VM with HTTPS

Phones only let a web page use the camera and microphone on a secure page (`https://`, or `localhost`).
To use MemoryAtlas from your phone, run it on a VM behind a name that has a certificate. This
describes the setup with a free [DuckDNS](https://www.duckdns.org) name; any domain that points at the
VM works the same way.

The default `compose.yaml` only listens on `127.0.0.1`, on purpose. The app has no accounts and has demo
endpoints (reset, and ones that hand out consent revocation tokens). **Do not expose it to the internet
without the login in this guide.**

## What you need

- A VM with Docker and the compose plugin, and ports **80 and 443** open to the internet (firewall and
  cloud security group). Port 80 is used to obtain the certificate.
- A DuckDNS name (for example `mynotes.duckdns.org`) pointing at the VM's public IP.
- A Meta model key, so the app runs in live mode. Adding memories does not work in replay mode.

## Steps

1. Clone the repository on the VM and create `.env` from `.env.example`.

2. Make a password hash for the login (Caddy's own tool):

   ```bash
   docker run --rm caddy:2 caddy hash-password
   ```

3. Fill in `.env`. **Write every `$` in the hash as `$$`** (compose treats a single `$` as a variable):

   ```bash
   MEMORYATLAS_LLM_MODE=live
   MODEL_API_KEY=...                 # your key
   MEMORYATLAS_SECRET=...            # a long random string; keys the revocation tokens
   PUBLIC_HOST=mynotes.duckdns.org
   BASIC_AUTH_USER=me
   BASIC_AUTH_HASH=$$2a$$14$$...     # the hash from step 2, with $ doubled
   ```

4. Start it:

   ```bash
   docker compose -f compose.yaml -f deploy/compose.public.yaml up -d --build
   ```

   The override file stops the web container publishing a port and adds Caddy, which gets a certificate
   for `PUBLIC_HOST` automatically and asks for the login on every page.

5. Open `https://mynotes.duckdns.org` on your phone, sign in, press **Add memory**, and allow the camera
   and microphone when the browser asks.

To go back to local-only: `docker compose down`, then `docker compose up -d`. Your data lives in the
`data` volume and is kept.

## Notes

- Caddy keeps its certificate in the `caddy_data` volume. Do not delete it on every deploy: certificate
  authorities rate-limit how often a name can be issued one.
- Uploads are limited to 100 MB per request by both Caddy and the web container.
- The login protects everything, including the demo endpoints. If more than one person will use this,
  put real accounts in front of it first. The basic-auth login is a single shared password.
- To try the proxy on a machine where ports 80 and 443 are taken, set `PUBLIC_HTTP_PORT` and
  `PUBLIC_HTTPS_PORT`. A real domain will not get a certificate on other ports.

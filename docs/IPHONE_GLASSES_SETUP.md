# Oakley HSTN → iPhone → MemoryAtlas: first real photo

This milestone uses a **native SwiftUI iPhone app**, Meta Wearables DAT **1.0.1**, and a small
authenticated backend gateway. It captures a still from the glasses' camera stream, lets you
review it, then sends it to the live memory compiler. It does not use the iPhone camera, record
audio, save photos to the camera roll, or upload automatically. A stream photo is the first
milestone; standalone full-resolution photo capture is a later improvement.

The Xcode project is `ios/MemoryAtlasPhone.xcodeproj`; select scheme **MemoryAtlasPhone**.
The code builds for iOS 17.2+, using Xcode 26.4 / Swift 6.3. A physical iPhone and HSTN are required
to verify real capture. A successful unsigned build does not establish hardware pairing or capture.

## 1. Prepare your glasses and iPhone

1. Pair your **Oakley Meta HSTN** with the Meta AI app on your iPhone and confirm they work there.
2. Update the glasses and Meta AI app. Enable **Developer Mode** for the glasses in Meta AI's device settings.
3. Connect the iPhone to this Mac with USB. Unlock it and accept **Trust This Computer** if asked.
4. In Xcode, add your Apple account under **Settings → Accounts**. Select your own development team.
5. Enable iPhone **Developer Mode** under **Settings → Privacy & Security**, restarting if requested.
   Keep phone Developer Mode and glasses Developer Mode distinct: both are needed for this development flow.

Meta's Developer Mode skips the need for a Meta app ID/client token in this sample-style flow.
Other release channels require credentials and configuration in Wearables Developer Center.
Apple signing/account agreements and device permission prompts must be completed by the device owner.

## 2. Configure the Mac backend

Install the regular local dependencies first (`make setup`; see LOCAL_SETUP.md).
Edit the git-ignored `.env` at the repository root. Keep your **Meta Model API key on the Mac**:

```dotenv
MEMORYATLAS_LLM_MODE=live
MODEL_API_KEY=your-real-meta-model-api-key
MEMORYATLAS_SECRET=your-random-local-revocation-secret
MEMORYATLAS_MOBILE_TOKEN=your-random-phone-access-token
MEMORYATLAS_MOBILE_HOST=0.0.0.0
```

Generate each random value separately, using:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

The phone access token must be at least 32 characters. Enter that token in the phone app; **do not
enter the model API key there**. Do not commit `.env`, paste keys into an issue/chat, or forward port 8001
to the public internet. The gateway is a single-owner prototype, not a multi-user authentication service.

Run these in separate terminals at the repository root:

```sh
make api         # existing Atlas API on localhost:8000; keep it loopback-only
make web         # browser UI at http://localhost:5173
make mobile-api  # bearer-protected phone gateway on port 8001
```

The two API processes share `backend/memoryatlas.db` by default. If setting MEMORYATLAS_DB,
use the **same absolute path** for both. This is what makes the phone's memories visible in the Atlas.
No second demo database is created by the gateway. Do not press Demo Reset after taking real photos:
the existing demo reset clears the shared database.

The `MEMORYATLAS_MOBILE_HOST=0.0.0.0` line deliberately makes **only the protected gateway** reachable on
your trusted LAN. Without it, the gateway stays at 127.0.0.1. The gateway does not expose `/demo/grants`,
`/graph`, `/export`, Swagger docs or the general capture API. Keep the regular API on localhost.

Find your Mac's local hostname:

```sh
scutil --get LocalHostName
```

If it prints `My-Mac`, the phone address is **`http://My-Mac.local:8001`**. Put the Mac and iPhone on
the same trusted Wi-Fi; allow the gateway through the macOS firewall if prompted. Guest Wi-Fi/client
isolation, VPNs, or a hotspot can prevent a connection. `localhost` on the phone is the phone itself.

The app permits HTTP only to local/private addresses. HTTP on Wi-Fi is unencrypted; use a trusted
development network. Use an authenticated HTTPS backend for anything remote. No public tunnel is
created by this feature. Redirects are refused so the phone token is not forwarded to a new location.

Real photos require **live** mode. Replay mode cannot process unseen pixels. Checking the connection
verifies mode/key presence without transmitting a photo; actual model access is exercised on upload.

## 3. Build and install the app

1. Open `ios/MemoryAtlasPhone.xcodeproj` in Xcode. Let Swift Package Manager resolve DAT 1.0.1.
2. Select the **MemoryAtlasPhone** target → **Signing & Capabilities**. Choose your Apple development
   team and replace `dev.memoryatlas.capture` with your own unique bundle identifier. Automatic signing is enabled.
3. Alternatively copy `ios/Local.xcconfig.example` to `ios/Local.xcconfig` and set team/bundle ID there.
   `Local.xcconfig` and Xcode's per-user settings are git-ignored. Do not commit personal signing changes.
4. Select your **physical iPhone**, scheme **MemoryAtlasPhone**, and press **Run**.
5. If Xcode says the iOS platform is unavailable, install its iOS component under **Settings → Components**.
   This Mac's generic iOS destination initially reported unavailable; the direct SDK build below succeeded.

The app declares Bluetooth, local-network and accessory transport permissions and a `memoryatlas://`
callback. These are necessary for Meta AI registration. It requests no microphone, location, or photo-library
permission. DAT analytics are opted out in Info.plist. Keep the URL scheme and MWDAT AppLinkURLScheme in sync.

## 4. Take your first real photo

1. In **MemoryAtlas Capture**, enter the Mac gateway address and **phone access token**.
2. Tap **Check connection & save token**. It must report **Live backend ready**. The token is saved in
   this device's Keychain; no model key is stored on the phone.
3. Tap **Connect glasses in Meta AI** and complete Meta's registration flow. Return to MemoryAtlas.
4. Wear the HSTN. Once it says **HSTN available**, tap **Start glasses session**.
5. Once connected, tap **Allow camera & start**. This may open Meta AI to request camera permission;
   grant it and return. Wait for **Glasses camera ready**.
6. Look at a clearly recognizable object, such as a wallet on a table or a printed sign. Tap
   **Capture photo from glasses**. The actual glasses image appears on the iPhone; the stream stops.
7. Review the image, enable **Allow this photo to be processed by my backend and Meta**, then tap
   **Send photo to MemoryAtlas**. This is the only point at which the photo leaves the phone for your backend.
8. Wait for **Memory stored**, an observation and a source ID. Open/refresh the Atlas on the Mac,
   clear any old answer focus, and select **Details** / **All facts as a table** to locate the new memory.

**Success means all three are verified:** the review image came from the HSTN, the backend returned a
nonempty compiled claim list, and that source's claims are visible in the shared Atlas graph. Do not count
a simulator build, a stock image, or a successful upload with zero claims as the hardware gate.

Take a second photo by discarding/sending the first, then starting the camera again. Capture time is
recorded when you press the glasses capture button, not when upload completes. The phone sends an
explicit UTC timestamp; the gateway converts it to the Mac's local wall time to match the existing engine.
GPS and spoken recall are intentionally not part of this first-photo milestone.

The app resizes images to at most 1600 pixels on the longest side, re-encodes JPEG without source
metadata, and holds the review image in memory. Sending/discarding/backgrounding clears the UI's image;
there are no app-level photo files, camera-roll writes, durable upload queues or automatic retries.
The backend passes the image to the model and stores text claims; the model provider's own retention
terms still apply. Runtime photo bytes are not an encrypted-memory/secure-erasure guarantee.

## API and failure handling

Every route requires `Authorization: Bearer <phone-token>`:

| Route | Behavior |
|---|---|
| GET /mobile/health | Verifies token, live mode and server-side key presence; reveals no credentials |
| POST /mobile/sessions | Creates a unique owner-consented capture session; returns grant and revocation token |
| POST /mobile/photos | Accepts session_id, timezone-aware captured_at and image_b64; returns source/claim confirmation |

A new consent grant is created when Send is tapped. This milestone has no phone revocation UI; it does not
change the existing revocation engine. Its grant is listed in the backend's consent API. Keep this a staged
development capture, not a production personal-memory archive, until the general consent UI and the
independent Phase 3 retention findings are addressed.

| Symptom | Next action |
|---|---|
| 401 | Check the phone token matches MEMORYATLAS_MOBILE_TOKEN; restart the gateway after changing .env |
| 409 | Switch backend from replay/record to live and restart |
| 503 | Set/check the model API key and model access on the Mac; retry when the provider is available |
| Cannot connect / local-network denied | Check Wi-Fi, Mac hostname, iPhone Local Network permission and firewall |
| No glasses available | Wear glasses, verify Meta AI pairing, enable glasses Developer Mode, update firmware |
| Meta app-on-glasses update required | Complete the update through Meta AI / Meta's official sample, reconnect |
| Photo timeout | Stop the session, reconnect and start the camera again |
| 422 / no memory compiled | Try a clearer scene; this is reported as failure rather than a false success |
| Upload interrupted | Check the Mac graph before retrying: the backend may have finished after the connection ended |

## Checks for developers

```sh
cd backend && .venv/bin/python -m pytest tests/test_mobile.py -q
cd ../ios/MemoryAtlasCore && swift test
```

Unsigned device SDK build (does not require signing, pairing or a connected phone):

```sh
xcodebuild -project ios/MemoryAtlasPhone.xcodeproj -target MemoryAtlasPhone \
  -configuration Debug -sdk iphoneos CODE_SIGNING_ALLOWED=NO \
  SYMROOT=/tmp/memoryatlas-ios-products OBJROOT=/tmp/memoryatlas-ios-objects build
```

The gateway's integration tests use a fake model with synthetic JPEG bytes to verify transport,
authorization, consent and compiler wiring. They are not a claim that a physical HSTN has been tested.
The pre-existing recall replay cache-miss errors in the full backend suite are independent of this feature.

## Official references

- [DAT iOS sample](https://github.com/meta/meta-wearables-dat-ios/tree/main/samples/CameraAccess)
- [Meta supported devices / developer setup](https://developers.meta.com/wearables/faq/)
- [Wearables developer documentation](https://wearables.developer.meta.com/docs/develop/)

The implementation was checked against the official SDK 1.0.1 interfaces and camera lifecycle. No Meta
sample media, binaries or personal credentials are vendored in this repository; Swift Package Manager
fetches the SDK under its own developer terms.

// End-to-end check that profiles are private, in a real browser. Optional: it needs Playwright, which is not
// a project dependency (it downloads browsers).
//
//   1. Start the backend with profiles on, in replay mode, on a scratch database (no API key needed):
//        cd backend && MEMORYATLAS_AUTH=on MEMORYATLAS_LLM_MODE=replay MEMORYATLAS_DB=/tmp/ma-profiles/x.db \
//          .venv/bin/uvicorn app.main:app --port 8000
//   2. Start the web UI:           make web
//   3. Install Playwright once:    cd frontend && npm install --no-save playwright && npx playwright install chromium
//   4. Run:                        cd frontend && npm run e2e:profiles
//
// Environment:  BASE_URL (default http://localhost:5173)
//
// It creates profiles with random names and leaves the last one locked, so use a scratch database. Exit code 0
// means every step held.
const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:5173";
const RUN = Math.random().toString(36).slice(2, 8);
const IP = `10.77.${Math.floor(Math.random() * 250)}.${Math.floor(Math.random() * 250)}`;   // a fresh address per run: sign-in limits are per IP
const PASS = "e2e-passcode-1";
const A = `Alice ${RUN}`, B = `Bruno ${RUN}`;

let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failures++; };

const profileMenu = (page) => page.locator('summary[aria-label^="Profile menu"]');
// The dashboard shows 0 until the graph has loaded, so wait for facts to appear rather than read once.
const hasFacts = (page) => page.waitForFunction(() => Number(document.querySelector(".kpi b")?.textContent) > 0, null, { timeout: 20000 })
  .then(() => true, () => false);
const graphNodes = (page) => page.evaluate(async () => (await (await fetch("/api/graph")).json()).nodes.length);

async function signUp(page, name) {
  await page.goto(BASE + "/");
  await page.getByRole("tab", { name: "Create profile" }).click();
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Passcode", { exact: true }).fill(PASS);
  await page.getByRole("button", { name: "Create profile" }).click();
}

async function onboard(page, firstMemory) {
  await page.getByRole("heading", { name: /How do you want to use/ }).waitFor();
  await page.getByLabel(/Remember my day/).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("heading", { name: "What you are agreeing to" }).waitFor();
  for (const box of await page.locator(".onb-check input").all()) await box.check();
  await page.getByRole("button", { name: "I agree" }).click();
  await page.getByRole("heading", { name: "Add your first memory" }).waitFor();
  await page.getByRole("button", { name: firstMemory }).click();
  await page.locator(".header").waitFor({ timeout: 120000 });
}

async function signOut(page) {
  await profileMenu(page).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("tab", { name: "Sign in" }).waitFor();
}

async function signIn(page, name, passcode) {
  await page.getByRole("tab", { name: "Sign in" }).click();
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Passcode", { exact: true }).fill(passcode);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, extraHTTPHeaders: { "X-Forwarded-For": IP } });
  const page = await ctx.newPage();

  // A signs up and loads the sample day.
  await signUp(page, A);
  await onboard(page, /Try the sample day/);
  check(await hasFacts(page), "A's dashboard shows remembered facts after the sample day");
  const aNodes = await graphNodes(page);
  check(aNodes > 0, `A's graph has ${aNodes} nodes`);
  check((await page.getByRole("button", { name: "Reset" }).count()) === 0, "a normal profile has no Reset button");
  await signOut(page);
  check((await page.locator(".kpi").count()) === 0, "after sign out the dashboard is gone");

  // B signs up and sees nothing of A's.
  await signUp(page, B);
  await onboard(page, "Skip for now");
  check(await page.getByRole("heading", { name: "Your memory is empty" }).isVisible() && (await page.locator(".kpi b").first().innerText()).trim() === "0", "B's dashboard shows no facts");
  check((await graphNodes(page)) === 0, "B's graph is empty (none of A's nodes)");
  await signOut(page);

  // A comes back to the same content.
  await signIn(page, A, PASS);
  await page.locator(".kpi").first().waitFor();
  check((await hasFacts(page)) && (await graphNodes(page)) === aNodes, "A signs in again and the same content is there");
  await signOut(page);

  // A wrong passcode gives the generic message, for a real name and an unknown one alike.
  await signIn(page, A, "not-the-passcode");
  const wrong = await page.getByRole("alert").innerText();
  await page.getByLabel("Name", { exact: true }).fill(`Nobody ${RUN}`);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForTimeout(400);
  const unknown = await page.getByRole("alert").innerText();
  check(/do not match/.test(wrong) && wrong === unknown, "wrong passcode and unknown name show the same message");

  // B deletes the profile with the passcode; it cannot sign in afterwards.
  await signIn(page, B, PASS);
  await page.locator(".kpi").first().waitFor();
  await profileMenu(page).click();
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Delete my profile…" }).click();
  await page.getByLabel("Type your passcode to confirm").fill(PASS);
  await page.getByRole("button", { name: "Delete everything" }).click();
  await page.getByRole("tab", { name: "Sign in" }).waitFor();
  await signIn(page, B, PASS);
  await page.getByRole("alert").waitFor();
  check(/do not match/.test(await page.getByRole("alert").innerText()), "a deleted profile cannot sign in");

  // Somebody with no session cannot read A's graph.
  const stranger = await browser.newContext({ extraHTTPHeaders: { "X-Forwarded-For": IP } });
  const res = await stranger.request.get(BASE + "/api/graph");
  check(res.status() === 401, "a browser with no session gets 401 for the graph");
  await stranger.close();

  // Five wrong passcodes lock the profile, and say so.
  for (let i = 0; i < 5; i++) {
    await signIn(page, A, `wrong-${i}-passcode`);
    await page.waitForTimeout(250);
  }
  await signIn(page, A, PASS);                       // the right one is refused too
  await page.waitForTimeout(400);
  check(/Too many attempts/.test(await page.getByRole("alert").innerText()), "five wrong passcodes lock the profile, even for the right one");

  await browser.close();
  console.log(failures === 0 ? "All steps held" : `${failures} step(s) failed`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });

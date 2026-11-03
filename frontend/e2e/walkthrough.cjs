// End-to-end check of the whole demo in a real browser. Optional: it needs Playwright, which is
// not a project dependency (it downloads browsers).
//
//   1. Start the backend in replay mode (no API key needed):   make api
//   2. Start the web UI:                                        make web
//   3. Install Playwright once:   cd frontend && npm install --no-save playwright && npx playwright install chromium
//   4. Run:                       cd frontend && npm run e2e
//
// Environment:  BASE_URL (default http://localhost:5173)
//               AXE_PATH  path to axe.min.js to also run an accessibility audit (optional)
//
// It RESETS the demo state first. Exit code 0 means every step held.
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = process.env.BASE_URL || "http://localhost:5173";
const AXE = process.env.AXE_PATH && fs.existsSync(process.env.AXE_PATH) ? fs.readFileSync(process.env.AXE_PATH, "utf8") : null;

let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failures++; };

async function audit(page, label) {
  if (!AXE) return;
  await page.waitForTimeout(700); // let entrance animations finish: axe measures contrast mid-fade otherwise
  await page.evaluate(AXE);
  const v = await page.evaluate(async () => (await axe.run(document, { resultTypes: ["violations"] })).violations.map((x) => `${x.id} x${x.nodes.length}`));
  check(v.length === 0, `accessibility (axe): ${label}${v.length ? ` -> ${v.join(", ")}` : ""}`);
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const problems = [];
  // The browser logs the 503 for the deliberately unrecorded question; the app handles it, so it is expected.
  let expect503 = false;
  page.on("console", (m) => {
    if (!["error", "warning"].includes(m.type())) return;
    if (expect503 && /status of 503/.test(m.text())) return;
    problems.push(m.text());
  });
  page.on("pageerror", (e) => problems.push(e.message));

  await page.request.post(`${BASE}/api/demo/reset`);
  await page.goto(BASE);
  await page.waitForSelector("text=Replay mode");
  await page.getByRole("button", { name: "Atlas", exact: true }).click(); // the app opens on the Dashboard
  check(await page.locator("text=Raw media kept: 0 B").isVisible(), "header shows the model mode and 'Raw media kept: 0 B'");

  // Build the day.
  await page.getByRole("button", { name: "Play the day", exact: true }).click();
  await page.waitForSelector("text=Day played");
  check((await page.locator(".events .event:not(.future)").count()) === 5, "five scheduled events played; the live photo is still upcoming");
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await page.waitForTimeout(1200);
  await audit(page, "map view");

  // Act 2: a question no single source can answer, with its evidence.
  await page.locator(".examples button").first().click();
  await page.waitForSelector('.qa .a:has-text("Luna Taqueria")');
  check(true, "restaurant question answered: Luna Taqueria");
  check((await page.locator(".qa .chip", { hasText: "Answered" }).count()) === 1, "answer is marked 'Answered'");
  check((await page.locator(".cite", { hasText: "Inferred" }).count()) === 1, "the cited claim is marked 'Inferred'");
  await page.getByRole("button", { name: "Why? Show the evidence" }).click();
  await page.waitForSelector("dialog.drawer[open] .prov");
  const prov = await page.locator("dialog.drawer .prov").innerText();
  check(/Photo/.test(prov) && /Conversation/.test(prov) && /Calendar/.test(prov), "evidence traces to a photo, the conversation and the calendar");
  await audit(page, "evidence drawer open");
  await page.locator("dialog.drawer").getByRole("button", { name: "Close" }).click();

  // A question that was never recorded gets a friendly explanation and nearby questions, not a raw error.
  expect503 = true;
  await page.locator("#question").fill("Which gym membership did I buy last week?");
  await page.locator("#question").press("Enter");
  await page.waitForSelector("text=No recording for that question.");
  check((await page.locator(".not-recorded .examples button").count()) >= 1, "an unrecorded question explains itself and offers recorded ones");
  check((await page.locator(".qa .notice.error").count()) === 0, "...and shows no raw error");
  expect503 = false;

  // The timeline.
  await page.locator("#scrub").focus();
  await page.keyboard.press("Home");
  await page.waitForTimeout(500);
  check(!(await page.locator("#scrub").isDisabled()) && /09:10/.test(await page.locator(".timeline output").innerText()), "scrubbing back reaches the first moment (09:10)");
  await page.keyboard.press("End");

  // Act 3: a later photo corrects the wallet.
  await page.getByRole("button", { name: /Upload live photo/ }).click();
  await page.waitForSelector(".event:not(.future) >> text=17:45");
  await page.getByRole("group", { name: "Example questions" }).getByRole("button", { name: "Where is my wallet?" }).click();
  await page.waitForSelector('.qa .a:has-text("17:45")');
  const wallet = await page.locator(".qa .a").first().innerText();
  check(/Last confirmed sighting at 17:45/.test(wallet) && /09:10/.test(wallet), "wallet answer says 'Last confirmed sighting at 17:45' and keeps the café as history");

  // Act 4: Alex withdraws consent on the simulated phone, in a second tab.
  await page.getByRole("tab", { name: "Consent" }).click();
  const grants = await (await page.request.get(`${BASE}/api/consent/grants`)).json();
  const alex = grants.find((g) => g.grantor === "alex");
  const phone = await ctx.newPage();
  await phone.goto(`${BASE}/?as=device&grant=${alex.grant_id}`);
  await phone.waitForSelector(".phone h2");
  await audit(phone, "simulated phone page");
  await phone.getByRole("button", { name: /Withdraw my consent/ }).click();
  await phone.locator("#pin").fill("0000");
  await phone.getByRole("button", { name: "Withdraw", exact: true }).click();
  check(await phone.locator("text=That PIN is not right").isVisible(), "a wrong PIN is refused and nothing is withdrawn");
  await phone.locator("#pin").fill("4242");
  await phone.getByRole("button", { name: "Withdraw", exact: true }).click();
  await phone.waitForSelector("text=It's been forgotten");
  await page.bringToFront();
  await page.waitForSelector("dialog[open] >> text=Forgetting receipt", { timeout: 20000 });
  check(await page.locator("dialog[open] >> text=7 of 7 checks passed").isVisible(), "the first tab shows the receipt on its own: 7 of 7 checks passed");
  const receipt = await page.locator("dialog[open]").innerText();
  check(/Me met with Alex/.test(receipt) && /Calendar at 12:30/.test(receipt), "receipt: 'Me met with Alex' is kept because the calendar still supports it");
  check(!/pastor|proposal|Friday/i.test(receipt), "receipt does not repeat anything that was forgotten");
  await audit(page, "receipt dialog open");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  check((await page.locator("dialog[open]:has-text('Forgetting receipt')").count()) === 0, "Esc closes the receipt");
  await phone.close();

  // After forgetting.
  await page.getByRole("tab", { name: "Ask" }).click();
  await page.getByRole("group", { name: "Example questions" }).getByRole("button", { name: "What did Alex promise me?" }).click();
  await page.waitForSelector('.qa:has-text("What did Alex promise me?") .a');
  check(/no record/i.test(await page.locator(".qa:has-text('What did Alex promise me?') .a").innerText()), "'What did Alex promise me?' now answers that there is no record");
  await page.getByRole("group", { name: "Example questions" }).getByRole("button", { name: "What colour is the awning at Luna Taqueria?" }).click();
  await page.waitForSelector('.qa:has-text("awning") .a:has-text("green")');
  check(true, "the awning (supported by the sign photo) is still answered");
  await page.getByRole("tab", { name: "Facts" }).click();
  const table = await page.locator("#panel-facts .fact-list").allInnerTexts().then((t) => t.join(" "));
  check(!/recommended|committed to|said/.test(table) && /met with/.test(table), "facts tab: no conversation facts left, 'met with' remains");

  // Theme.
  await page.getByRole("button", { name: "Dark", exact: true }).click();
  await page.waitForTimeout(600);
  check(await page.evaluate(() => document.documentElement.getAttribute("data-theme")) === "dark", "the Dark switch sets the dark appearance");
  await audit(page, "dark theme");
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  await page.waitForSelector("text=Your memory at a glance");
  await page.waitForSelector("text=Latest forgetting", { timeout: 10000 });
  check(await page.locator("text=7/7").isVisible(), "dashboard shows the latest forgetting with 7/7 leak checks");

  // Correcting a memory. Replay mode has one recorded correction, so start again from a clean day
  // (the forgetting run above changed the graph that the recording assumes).
  await page.request.post(`${BASE}/api/demo/reset`);
  await page.reload();
  await page.waitForSelector("text=Replay mode");
  await page.getByRole("button", { name: "Atlas", exact: true }).click();
  await page.getByRole("button", { name: "Play the day", exact: true }).click();
  await page.waitForSelector("text=Day played");
  await page.getByRole("button", { name: /Upload live photo/ }).click();
  await page.waitForSelector(".event:not(.future) >> text=17:45");
  await page.getByRole("tab", { name: "Ask" }).click();
  await page.getByRole("button", { name: "What did Alex promise me?" }).click();
  await page.waitForSelector('.qa:has-text("What did Alex promise me?") .a:has-text("Friday")');
  check(true, "before the correction: 'What did Alex promise me?' answers Friday");
  await page.locator(".qa .cite").first().click();
  await page.getByRole("button", { name: "That's wrong…" }).click();
  await page.getByRole("button", { name: "Use the recorded example" }).click();
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
  await audit(page, "correction form open");
  await page.getByRole("button", { name: "Replace this fact" }).click();
  await page.waitForSelector("text=Correction recorded", { state: "attached" });
  await page.getByRole("button", { name: "What did Alex promise me?" }).click();
  await page.waitForSelector('.qa:has-text("What did Alex promise me?") .a:has-text("Monday")');
  const promised = await page.locator(".qa .a").first().innerText();
  check(/Monday/.test(promised) && !/Friday/.test(promised), `after the correction: the answer says Monday and no longer Friday (got: ${promised})`);
  await audit(page, "after a correction");

  // Consent that lapses. Start again from a clean day: expiry runs the same purge as a withdrawal, so the
  // recorded forgetting run serves it, but only on the graph it was recorded against.
  await page.request.post(`${BASE}/api/demo/reset`);
  await page.reload();
  await page.waitForSelector("text=Replay mode");
  await page.getByRole("button", { name: "Atlas", exact: true }).click();
  await page.getByRole("button", { name: "Play the day", exact: true }).click();
  await page.waitForSelector("text=Day played");
  await page.getByRole("button", { name: /Upload live photo/ }).click();
  await page.waitForSelector(".event:not(.future) >> text=17:45");
  await page.getByRole("tab", { name: "Consent" }).click();
  const alexCard = page.locator("li.grant", { hasText: "Alex" });
  await alexCard.getByRole("button", { name: /Let it expire now/ }).click();
  await page.waitForSelector("dialog[open] >> text=Forgetting receipt", { timeout: 20000 });
  const lapsed = await page.locator("dialog[open]").innerText();
  check(/consent expired/i.test(lapsed) && !/withdrew/i.test(lapsed), "the receipt says the consent expired, not that it was withdrawn");
  check(await page.locator("dialog[open] >> text=7 of 7 checks passed").isVisible(), "an expiry shows 7 of 7 checks passed");
  check(!/pastor|proposal|Friday/i.test(lapsed), "the expiry receipt repeats nothing that was forgotten");
  await audit(page, "expiry receipt open");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  check(await alexCard.locator(".chip", { hasText: "Expired" }).isVisible(), "Alex's grant now shows as Expired");
  await page.getByRole("tab", { name: "Ask" }).click();
  await page.getByRole("button", { name: "What did Alex promise me?" }).click();
  await page.waitForSelector('.qa:has-text("What did Alex promise me?") .a');
  check(/no record/i.test(await page.locator(".qa .a").first().innerText()), "after the expiry, 'What did Alex promise me?' says there is no record");

  check(problems.length === 0, `no console errors or warnings${problems.length ? ": " + problems.join(" | ") : ""}`);
  await browser.close();
  console.log(failures === 0 ? "\nAll steps held." : `\n${failures} step(s) failed.`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error("SCRIPT FAILED:", e.message.split("\n").slice(0, 3).join(" ")); process.exit(2); });

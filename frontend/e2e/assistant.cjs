// End-to-end check of the dashboard and the shared assistant, with a fresh profile each run. Optional: it needs
// Playwright, which is not a project dependency.
//
//   1. Start the backend with profiles ON, in replay mode, on a scratch data directory (no API key needed):
//        cd backend && MEMORYATLAS_AUTH=on MEMORYATLAS_LLM_MODE=replay MEMORYATLAS_DATA_DIR=/tmp/ma-assistant \
//          MEMORYATLAS_DB=/tmp/ma-assistant/unused.db .venv/bin/uvicorn app.main:app --port 8000
//   2. Start the web UI:        make web
//   3. Install Playwright once: cd frontend && npm install --no-save playwright && npx playwright install chromium
//   4. Run:                     cd frontend && npm run e2e:assistant
//
// Environment: BASE_URL (default http://localhost:5173). It creates a profile with a random name and leaves it
// behind, so use a scratch data directory. Exit code 0 means every step held.
//
// Replay mode answers only recorded questions, so the assistant is asked the recorded restaurant question.
const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:5173";
const QUESTION = "Which restaurant did Alex recommend when we met near the office?";

let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"}  ${what}`); if (!ok) failures++; };

async function openAssistant(page) {
  const panel = page.getByRole("dialog", { name: "Ask your memory" });
  if (!(await panel.isVisible())) await page.getByRole("button", { name: /Ask your memory/ }).click();
  await panel.waitFor();
  return panel;
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const problems = [];
  // The first page load has no session yet, so /auth/me answers 401 once: that is the sign-in screen, not a fault.
  page.on("console", (m) => { if ((m.type() === "error" || m.type() === "warning") && !/status of 401/.test(m.text())) problems.push(m.text()); });
  page.on("pageerror", (e) => problems.push(e.message));

  try {
    // A fresh profile, onboarded, with the sample day loaded from its snapshot (no model call).
    await page.goto(BASE);
    const status = await page.evaluate(async () => {
      const send = (path, body) => fetch("/api" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined }).then((r) => r.status);
      const name = "Assistant Check " + Math.random().toString(36).slice(2, 8);
      return [await send("/auth/signup", { name, passcode: "assistant-check-1" }), await send("/auth/goals", { goals: ["remember_day"], answers: {} }),
              await send("/auth/consent"), await send("/demo/load-sample")];
    });
    check(status.join(",") === "201,200,200,200", "a fresh profile with the sample day is ready");
    await page.goto(BASE);

    // The dashboard: coverage, model activity, to-dos.
    await page.locator(".cov-figs").waitFor();
    check(await page.locator(".cov-figs").getByText("25%").isVisible(), "the coverage strip shows 25% of waking hours");
    check(await page.locator(".cov-figs").getByText("4 h 25 min").isVisible(), "...and the longest gap, 4 h 25 min");
    check(await page.getByRole("heading", { name: "What the models processed" }).isVisible(), "the model activity card is there");
    await page.getByText("No model calls recorded yet").waitFor();
    check(true, "...and says plainly that nothing has been recorded yet");
    await page.getByText("No promises or requests found in your memories.").waitFor();
    check(true, "the to-do card shows its empty state");

    // Ask from the launcher.
    const panel = await openAssistant(page);
    await panel.locator("#question").fill(QUESTION);
    await panel.locator("#question").press("Enter");
    await page.waitForSelector('.assistant .qa .a:has-text("Luna Taqueria")');
    check(true, "the assistant answers: Luna Taqueria");
    check((await panel.locator(".qa .cite").count()) >= 1, "...with a receipt chip for the memory behind it");

    // Escape closes it, the launcher comes back, and the same conversation is there on the Atlas.
    await page.keyboard.press("Escape");
    check(await page.getByRole("button", { name: /Ask your memory/ }).isVisible(), "Escape closes the panel and the launcher returns");
    await page.getByRole("button", { name: "Atlas", exact: true }).click();
    const onAtlas = await openAssistant(page);
    check(await onAtlas.locator(".q.bubble", { hasText: QUESTION }).first().isVisible(), "on the Atlas the same conversation is there");

    // Cmd/Ctrl+K toggles it.
    await page.keyboard.press("Control+k");
    check(!(await page.getByRole("dialog", { name: "Ask your memory" }).isVisible()), "Ctrl+K closes it");
    await page.keyboard.press("Control+k");
    check(await page.getByRole("dialog", { name: "Ask your memory" }).isVisible(), "...and opens it again");

    // Reload: the conversation is kept.
    await page.reload();
    const reloaded = await openAssistant(page);
    await reloaded.locator(".q.bubble", { hasText: QUESTION }).first().waitFor();
    check(true, "after a reload the conversation is still there");

    // The usage shows on the dashboard now.
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Dashboard", exact: true }).click();
    await page.getByRole("heading", { name: "What the models processed" }).waitFor();
    await page.waitForTimeout(800);
    check(!(await page.getByText("No model calls recorded yet").isVisible()), "the model card now shows the call the question made");

    check(problems.length === 0, `no console errors or warnings${problems.length ? ": " + problems.slice(0, 3).join(" | ") : ""}`);
  } catch (e) {
    failures++;
    console.log("SCRIPT FAILED:", String(e).split("\n").slice(0, 2).join(" "));
  }
  await browser.close();
  console.log(failures ? `${failures} step(s) failed` : "All steps held.");
  process.exit(failures ? 1 : 0);
})();

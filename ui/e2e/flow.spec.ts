import { readFileSync } from "node:fs";
import { test, expect, type Page } from "@playwright/test";
import { axe, login, noSideScroll, shot, tabTo } from "./helpers";

// S13 checkpoints on the live platform. One serial story, keyboard only:
//   CP13.1 store logs in, creates a ticket, sees the first step, replies, sees the next.
//   CP13.2 L2 approves the supervised action; the store chat shows the grey IT line
//          within 4 s; a stale second approve shows "already handled"; vendor can't see it.
//   CP13.3 screenshots at 1280 and 390 px, no side scroll at 390, axe clean on every screen.
const fixture = JSON.parse(readFileSync("../tests/fixtures/new_printer_ticket.json", "utf8")) as {
  ticket: { subject: string; description: string; asset_id: string };
  script: { store_reply_before_action: string };
};
const STORE = "store-sw-0003";
const AGENT_WAIT = 240_000; // the agent's LLM turns

let store: Page;
let ticketId = "";

const agentBubbles = (p: Page) => p.locator(".bubble.agent");
const itLines = (p: Page) => p.locator(".itline");
const statusWith = (p: Page) => p.locator(".statusbar div", { hasText: "With" }).locator("dd");

test.describe.serial("Demo UI", () => {
  test("login page is accessible", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await shot(page, "1280-login");
    await axe(page, "login");
  });

  test("CP13.1 store creates a ticket and follows the walk", async ({ browser }) => {
    store = await login(browser, STORE);
    await expect(store.getByRole("heading", { name: "My tickets" })).toBeVisible();
    await axe(store, "store home");

    await tabTo(store, /New ticket/);
    await store.keyboard.press("Enter");
    await expect(store.getByRole("heading", { name: "New ticket" })).toBeVisible();
    await store.keyboard.type(fixture.ticket.subject); // focus starts on Subject
    await store.keyboard.press("Tab");
    await store.keyboard.type(fixture.ticket.description);
    await store.keyboard.press("Tab");
    await store.keyboard.type(fixture.ticket.asset_id);
    await shot(store, "1280-new-ticket");
    await axe(store, "new ticket");
    await tabTo(store, /Create ticket/);
    await store.keyboard.press("Enter");

    const head = store.locator(".ticket-head .meta");
    await expect(head).toHaveText(/^SWT-/, { timeout: 20_000 });
    ticketId = (await head.textContent()) ?? "";
    console.log(`ticket ${ticketId}`);

    // First runbook step with its source under it.
    await expect(store.locator(".bubble.agent .source").first()).toBeVisible({ timeout: AGENT_WAIT });
    await expect(store.locator("#reply")).toBeEnabled({ timeout: AGENT_WAIT });
    await shot(store, "1280-chat-first-step");
    await axe(store, "ticket chat");

    const before = await agentBubbles(store).count();
    await tabTo(store, /Your reply/);
    await store.keyboard.type(fixture.script.store_reply_before_action);
    await store.keyboard.press("Control+Enter");
    await expect(store.locator(".bubble.store", { hasText: "self-test page printed" })).toBeVisible({
      timeout: AGENT_WAIT,
    });
    await expect.poll(() => agentBubbles(store).count(), { timeout: AGENT_WAIT }).toBeGreaterThan(before);
    await shot(store, "1280-chat-next-step");
  });

  test("CP13.2 L2 approves from the queue and the store chat updates", async ({ browser }) => {
    // Answer further store steps the same way until the walk asks IT for approval.
    for (let i = 0; i < 6; i++) {
      await expect
        .poll(async () => (await statusWith(store).textContent()) ?? "", { timeout: AGENT_WAIT })
        .toMatch(/IT approval|reply needed|L2 engineer/i);
      const holder = (await statusWith(store).textContent()) ?? "";
      if (/IT approval/.test(holder)) break;
      if (/L2 engineer/.test(holder)) throw new Error("walk went to an L2 task, not an approval");
      const n = await agentBubbles(store).count();
      await store.locator("#reply").fill(fixture.script.store_reply_before_action);
      await store.keyboard.press("Control+Enter");
      await expect.poll(() => agentBubbles(store).count(), { timeout: AGENT_WAIT }).toBeGreaterThan(n);
    }
    await expect(statusWith(store)).toHaveText(/IT approval/);

    // The vendor approver must not see an l2 card.
    const vendor = await login(browser, "vendor-approver");
    await expect(vendor.getByRole("heading", { name: /Needs approval/ })).toBeVisible();
    await vendor.waitForTimeout(2500);
    await expect(vendor.locator(".ticket-row", { hasText: ticketId })).toHaveCount(0);

    // A second L2 view frozen on the same card, to make a stale approve (D53).
    const stale = await login(browser, "l2-engineer");
    await stale.locator(".ticket-row", { hasText: ticketId }).click({ timeout: AGENT_WAIT });
    await expect(stale.getByRole("heading", { name: "Step to approve" })).toBeVisible();
    await stale.route(/localhost:8000\/tickets(\/[^/]+)?$/, (route) =>
      route.request().method() === "GET" ? route.abort() : route.continue(),
    );

    const l2 = await login(browser, "l2-engineer");
    await expect(l2.locator(".ticket-row", { hasText: ticketId })).toBeVisible({ timeout: AGENT_WAIT });
    await shot(l2, "1280-queue");
    await axe(l2, "queue");
    await tabTo(l2, new RegExp(ticketId));
    await l2.keyboard.press("Enter");
    await expect(l2.getByRole("heading", { name: "Step to approve" })).toBeVisible();
    await expect(l2.locator(".card code").first()).not.toHaveText("—");
    await shot(l2, "1280-approval-card");
    await axe(l2, "approval card");

    const lines = await itLines(store).count();
    await tabTo(l2, /^Approve$/);
    const t0 = Date.now();
    await l2.keyboard.press("Enter");
    await expect.poll(() => itLines(store).count(), { timeout: 4_000, intervals: [250] }).toBeGreaterThan(lines);
    console.log(`grey IT line after ${Date.now() - t0} ms`);
    await expect(l2.getByRole("status")).toContainText("approved");
    await shot(store, "1280-chat-after-approval");

    await stale.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(stale.getByRole("status")).toContainText("This was already handled");
    const focused = await stale.evaluate(() => document.activeElement?.textContent ?? "");
    expect(focused).toMatch(/Queue|SWT-/);
  });

  test("CP13.3 phone width: no side scroll, accessible", async ({ browser }) => {
    const phone = await login(browser, STORE, 390);
    await noSideScroll(phone);
    await shot(phone, "390-store-list");
    await axe(phone, "phone store list");
    await phone.locator(".ticket-row", { hasText: ticketId }).click();
    await expect(phone.locator(".chat")).toBeVisible();
    await noSideScroll(phone);
    await shot(phone, "390-chat");
    await axe(phone, "phone chat");
    await phone.getByRole("button", { name: "← Tickets" }).click();
    await phone.getByRole("button", { name: "New ticket" }).click();
    await noSideScroll(phone);
    await shot(phone, "390-new-ticket");

    const q = await login(browser, "l2-engineer", 390);
    await noSideScroll(q);
    await shot(q, "390-queue");
    await axe(q, "phone queue");
  });
});

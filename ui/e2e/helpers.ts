import { createHmac } from "node:crypto";
import { expect, type Browser, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/** The Demo UI password for a realm person (platform/realm.py person_password, D63). */
export function password(username: string): string {
  const key = process.env.MOCK_CLIENT_SECRET_KEY;
  if (!key) throw new Error("MOCK_CLIENT_SECRET_KEY is not set");
  return createHmac("sha256", key).update(`person:${username}`).digest("hex").slice(0, 16);
}

/** PKCE login through the Keycloak page, keyboard only. */
export async function login(browser: Browser, username: string, width = 1280): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } });
  const page = await ctx.newPage();
  await page.goto("/");
  const signIn = page.getByRole("button", { name: "Sign in with ServeWell ID" });
  await signIn.focus();
  await page.keyboard.press("Enter");
  await page.waitForURL(/localhost:8080/);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password(username));
  await page.keyboard.press("Enter");
  await page.waitForURL("http://localhost:5173/**");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  return page;
}

export async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `test-results/screens/${name}.png`, fullPage: true });
}

/** axe-core WCAG 2.1 A/AA (contrast, names, keyboard reachability) on the page as shown. */
export async function axe(page: Page, label: string): Promise<void> {
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = res.violations.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.help}`);
  expect(bad, bad.join("\n")).toEqual([]);
}

/** No horizontal page scroll (CP13.3, 390 px). */
export async function noSideScroll(page: Page): Promise<void> {
  const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(sw, `scrollWidth ${sw} > clientWidth ${cw}`).toBeLessThanOrEqual(cw);
}

/** Tab until the focused element matches, like a keyboard user would. */
export async function tabTo(page: Page, accessibleName: RegExp, max = 40): Promise<void> {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const name = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return "";
      const label = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent : null;
      return [el.getAttribute("aria-label"), label, el.closest("label")?.textContent, el.textContent, (el as HTMLInputElement).placeholder]
        .filter(Boolean)
        .join(" | ");
    });
    if (accessibleName.test(name)) return;
  }
  throw new Error(`keyboard focus never reached ${accessibleName}`);
}

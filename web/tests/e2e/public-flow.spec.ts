import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    if (route.request().url().endsWith("/auth/config")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          mode: "email_password",
          registration_enabled: true,
          email_verification_required: true,
          smtp_configured: true,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: "Authentication required." }),
    });
  });
});

test("public pages are navigable and responsive", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Planora home" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /timetabling built for academia/i })).toBeVisible();
  await expect(page.getByRole("banner").getByRole("button", { name: /sign in/i })).toBeVisible();
  await page.getByRole("dialog", { name: "Cookie notice" }).getByRole("button", { name: "Essential only" }).click();

  const previewButton = page.getByRole("button", { name: "Improve preview" });
  await expect(previewButton).toBeVisible();
  await page.screenshot({ path: "artifacts/screenshots/web-public-light.png", fullPage: false });
  await previewButton.click();
  await expect(page.getByText("Conflict repaired", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reset preview" })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.waitForTimeout(300);
  await page.screenshot({ path: "artifacts/screenshots/web-public-dark.png", fullPage: false });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: /timetabling built for academia/i })).toBeVisible();
  const mobileWidth = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(mobileWidth.document).toBeLessThanOrEqual(mobileWidth.viewport);
  await page.screenshot({ path: "artifacts/screenshots/web-public-mobile-dark.png", fullPage: false });
  await page.setViewportSize({ width: 1280, height: 900 });

  await page.getByRole("contentinfo").getByRole("button", { name: /faq/i }).click();
  await expect(page).toHaveURL(/\/faq$/);
  await expect(page.getByRole("heading", { name: "FAQ" })).toBeVisible();

  await page.getByRole("contentinfo").getByRole("button", { name: /privacy/i }).click();
  await expect(page).toHaveURL(/\/privacy$/);
  await expect(page.getByRole("heading", { name: "Privacy" })).toBeVisible();

  await page.getByRole("banner").getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
});

test("login page switches between account flows", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /register/i }).click();
  await expect(page.getByRole("heading", { name: /create account/i })).toBeVisible();
  await expect(page.getByLabel("Display name")).toBeVisible();

  await page.getByRole("main").getByRole("button", { name: /sign in/i }).click();
  await page.getByRole("button", { name: /reset it/i }).click();
  await expect(page.getByRole("heading", { name: /reset password/i })).toBeVisible();
});

test("public layouts do not overflow at the configured viewport", async ({ page }) => {
  for (const path of ["/", "/faq", "/privacy", "/login"]) {
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
    }));
    expect(dimensions.document, `${path} should fit the viewport`).toBeLessThanOrEqual(dimensions.viewport);
  }
});

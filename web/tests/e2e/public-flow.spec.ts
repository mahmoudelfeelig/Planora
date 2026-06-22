import { expect, test } from "@playwright/test";

test("public pages are navigable and responsive", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Planora home" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /explainable scheduling/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /login/i })).toBeVisible();

  await page.getByRole("button", { name: /faq/i }).click();
  await expect(page).toHaveURL(/\/faq$/);
  await expect(page.getByRole("heading", { name: "FAQ" })).toBeVisible();

  await page.getByRole("banner").getByRole("button", { name: /privacy/i }).click();
  await expect(page).toHaveURL(/\/privacy$/);
  await expect(page.getByRole("heading", { name: "Privacy" })).toBeVisible();

  await page.getByRole("button", { name: /login/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
});

test("login page switches between account flows", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /register/i }).click();
  await expect(page.getByRole("heading", { name: /create account/i })).toBeVisible();
  await expect(page.getByLabel("Display name")).toBeVisible();

  await page.getByRole("button", { name: /sign in/i }).click();
  await page.getByRole("button", { name: /reset it/i }).click();
  await expect(page.getByRole("heading", { name: /reset password/i })).toBeVisible();
});

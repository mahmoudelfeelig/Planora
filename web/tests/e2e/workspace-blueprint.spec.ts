import { expect, test, type Page } from "@playwright/test";

async function workspaceContrastFailures(page: Page) {
  return page.evaluate(() => {
    const visible = (element: Element): element is HTMLElement => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    };
    const rgb = (value: string): [number, number, number, number] | null => {
      const match = value.match(/rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)(?:[, /]+([\d.]+))?\)/);
      return match
        ? [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])]
        : null;
    };
    const luminance = ([red, green, blue]: [number, number, number]) => {
      const channels = [red, green, blue].map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    };
    const background = (element: Element): [number, number, number] => {
      let current: Element | null = element;
      while (current) {
        const color = rgb(getComputedStyle(current).backgroundColor);
        if (color && color[3] >= 0.95) return [color[0], color[1], color[2]];
        current = current.parentElement;
      }
      return [255, 255, 255];
    };
    return [...document.querySelectorAll("main *, header *, nav *")]
      .filter(visible)
      .filter((element) => [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()))
      .flatMap((element) => {
        const style = getComputedStyle(element);
        const foreground = rgb(style.color);
        if (!foreground || foreground[3] < 0.95) return [];
        const first = luminance([foreground[0], foreground[1], foreground[2]]);
        const second = luminance(background(element));
        const ratio = (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
        const fontSize = Number.parseFloat(style.fontSize);
        const fontWeight = Number.parseInt(style.fontWeight, 10) || 400;
        const minimum = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700) ? 3 : 4.5;
        return ratio + 0.01 < minimum
          ? [
              `${element.tagName.toLowerCase()}.${(element as HTMLElement).className} ` +
                `"${element.textContent?.trim().slice(0, 48)}": ${ratio.toFixed(2)} ` +
                `(${style.color} on ${getComputedStyle(element).backgroundColor})`,
            ]
          : [];
      });
  });
}

test("authenticated academic blueprint supports the core planning path", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/workspace");

  const tutorial = page.getByRole("dialog", { name: /your timetable, from data to publish/i });
  await expect(tutorial).toBeVisible();
  await expect(tutorial.getByText(/Step 1 of 5/i)).toBeVisible();
  await expect(tutorial.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect.poll(() => page.evaluate(() => document.activeElement?.closest('[role="dialog"]') !== null)).toBe(true);
  await page.screenshot({ path: "artifacts/screenshots/web-tutorial-light.png", fullPage: false });
  await tutorial.getByRole("button", { name: /skip to schedule/i }).click();
  await page.getByRole("button", { name: "Essential only", exact: true }).click();

  await page.getByRole("button", { name: /^Data/ }).click();
  await expect(page.getByText("Choose timetable data", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /open scenario/i }).first().click();
  await expect(page.getByText(/ready to build a draft/i)).toBeVisible();
  const loadedToast = page.locator(".toast").filter({ hasText: "Loaded" }).last();
  await expect(loadedToast).toBeVisible();
  await expect(loadedToast.getByRole("button", { name: "Open schedule" })).toBeVisible();
  await expect(loadedToast.locator(".toast-progress")).toBeVisible();
  await page.screenshot({ path: "artifacts/screenshots/web-toast-light.png", fullPage: false });
  await loadedToast.getByRole("button", { name: "Dismiss notification" }).click();

  await page.getByRole("button", { name: "Build schedule", exact: true }).click();
  await expect(page.getByText(/activities placed/i)).toBeVisible({ timeout: 45_000 });
  const firstClass = page.locator(".event").first();
  await expect(firstClass).toBeVisible();
  await firstClass.click();
  await expect(page.locator(".activity-inspector h2")).not.toHaveText("Select a class");

  await page.getByRole("button", { name: "Show suggestions" }).click();
  const keyboardTarget = page.getByRole("button", { name: /Move held class to THU, slot 1/i });
  await expect(keyboardTarget).toBeVisible();
  await keyboardTarget.focus();
  await keyboardTarget.press("Enter");
  await expect(page.getByText("Moved activity", { exact: true })).toBeVisible();
  const dismissToast = page.getByRole("button", { name: "Dismiss notification" }).last();
  await expect(dismissToast).toBeVisible();
  await dismissToast.click();
  await expect(page.getByText("Moved activity", { exact: true })).toBeHidden();

  await page.getByRole("button", { name: /^Review/ }).click();
  await expect(page.getByRole("heading", { name: "Conflicts & Diagnostics" })).toBeVisible();
  await page.getByRole("button", { name: /^Projects/ }).click();
  await expect(page.getByRole("heading", { name: "Projects", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Advanced/ }).click();
  await expect(page.getByRole("heading", { name: "Advanced", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Schedule/ }).click();
  await expect(page.locator(".blueprint-context strong")).toHaveText("Draft timetable");

  const dismissAllToasts = async () => {
    const dismissButtons = page.getByRole("button", { name: "Dismiss notification" });
    while (await dismissButtons.count()) await dismissButtons.first().click();
  };
  await dismissAllToasts();

  await page.setViewportSize({ width: 820, height: 1000 });
  await expect(page.locator(".activity-inspector")).toBeVisible();

  const bodyOverflow = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(bodyOverflow.width).toBeLessThanOrEqual(bodyOverflow.viewport + 1);
  await page.setViewportSize({ width: 480, height: 860 });
  const mobileScroll = page.locator(".schedule-scroll");
  await expect.poll(() => mobileScroll.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  await mobileScroll.evaluate((element) => {
    element.scrollLeft = 180;
    element.scrollTop = 160;
  });
  const scrollPosition = await mobileScroll.evaluate((element) => ({ left: element.scrollLeft, top: element.scrollTop }));
  expect(scrollPosition.left).toBeGreaterThan(0);
  expect(scrollPosition.top).toBeGreaterThan(0);
  const stickyHeaders = await page.evaluate(() => ({
    day: getComputedStyle(document.querySelector(".schedule-scroll thead th")!).position,
    time: getComputedStyle(document.querySelector(".schedule-scroll tbody th")!).position,
  }));
  expect(stickyHeaders).toEqual({ day: "sticky", time: "sticky" });
  await page.setViewportSize({ width: 1280, height: 900 });
  if (await page.locator("html").getAttribute("data-theme") === "dark") {
    await page.getByRole("button", { name: "Switch to light mode" }).click();
  }
  const lightContrast = await page.evaluate(() => {
    function luminance(value: string) {
      const parts = value.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [];
      const channels = parts.map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    }
    function ratio(selector: string) {
      const element = document.querySelector(selector) as HTMLElement | null;
      if (!element) return 0;
      const style = getComputedStyle(element);
      let background = style.backgroundColor;
      let parent = element.parentElement;
      while (background === "rgba(0, 0, 0, 0)" && parent) {
        background = getComputedStyle(parent).backgroundColor;
        parent = parent.parentElement;
      }
      const foregroundLuminance = luminance(style.color);
      const backgroundLuminance = luminance(background);
      return {
        selector,
        color: style.color,
        background,
        theme: document.documentElement.dataset.theme,
        parentClass: element.parentElement?.className || "",
        darkMatch: element.closest(".event")?.matches(':root[data-theme="dark"] .event') || false,
        ratio: (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
          (Math.min(foregroundLuminance, backgroundLuminance) + 0.05),
      };
    }
    return [
      ratio(".nav-page-context strong"),
      ratio(".schedule-scroll th"),
      ratio(".event strong"),
      ratio(".activity-inspector h2"),
      ratio(".tutorial-trigger"),
      ratio(".blueprint-actions button:first-child"),
    ];
  });
  expect(Math.min(...lightContrast.map((item) => item.ratio)), JSON.stringify(lightContrast)).toBeGreaterThanOrEqual(4.5);
  expect(await workspaceContrastFailures(page), "all light workspace text must meet WCAG AA contrast").toEqual([]);
  const desktopOverflow = await page.evaluate(() => ({
    documentHeight: document.documentElement.scrollHeight,
    viewportHeight: document.documentElement.clientHeight,
  }));
  expect(desktopOverflow.documentHeight).toBeLessThanOrEqual(desktopOverflow.viewportHeight + 1);
  await page.screenshot({ path: "artifacts/screenshots/web-blueprint-light.png", fullPage: false });

  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  for (const route of [
    { button: /^Data/, text: "Choose timetable data" },
    { button: /^Review/, text: "Conflicts & Diagnostics" },
    { button: /^Projects/, text: "Projects" },
    { button: /^Advanced/, text: "Advanced" },
  ]) {
    await page.getByRole("button", { name: route.button }).click();
    await expect(page.getByRole("heading", { name: route.text, exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: /^Schedule/ }).click();
  await expect(page.locator(".blueprint-context strong")).toHaveText("Draft timetable");
  await dismissAllToasts();
  await page.waitForTimeout(300);
  const darkContrast = await page.evaluate(() => {
    function luminance(value: string) {
      const parts = value.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [];
      const channels = parts.map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    }
    function ratio(selector: string) {
      const element = document.querySelector(selector) as HTMLElement | null;
      if (!element) return 0;
      const style = getComputedStyle(element);
      let background = style.backgroundColor;
      let parent = element.parentElement;
      while (background === "rgba(0, 0, 0, 0)" && parent) {
        background = getComputedStyle(parent).backgroundColor;
        parent = parent.parentElement;
      }
      const foregroundLuminance = luminance(style.color);
      const backgroundLuminance = luminance(background);
      return {
        selector,
        color: style.color,
        background,
        theme: document.documentElement.dataset.theme,
        parentClass: element.parentElement?.className || "",
        darkMatch: element.closest(".event")?.matches(':root[data-theme="dark"] .event') || false,
        ratio: (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
          (Math.min(foregroundLuminance, backgroundLuminance) + 0.05),
      };
    }
    return [
      ratio(".nav-page-context strong"),
      ratio(".schedule-scroll th"),
      ratio(".event strong"),
      ratio(".activity-inspector h2"),
      ratio(".tutorial-trigger"),
      ratio(".blueprint-actions button:first-child"),
    ];
  });
  expect(Math.min(...darkContrast.map((item) => item.ratio)), JSON.stringify(darkContrast)).toBeGreaterThanOrEqual(4.5);
  expect(await workspaceContrastFailures(page), "all dark workspace text must meet WCAG AA contrast").toEqual([]);
  await page.waitForTimeout(300);
  await page.screenshot({ path: "artifacts/screenshots/web-blueprint-dark.png", fullPage: false });

  await page.getByRole("button", { name: "How it works" }).click();
  await expect(tutorial).toBeVisible();
  await expect(tutorial.getByRole("button", { name: "Close" })).toBeFocused();
  for (let step = 1; step < 5; step += 1) {
    await tutorial.getByRole("button", { name: "Continue" }).click();
    await expect(tutorial.getByText(new RegExp(`Step ${step + 1} of 5`, "i"))).toBeVisible();
  }
  await page.screenshot({ path: "artifacts/screenshots/web-tutorial-dark.png", fullPage: false });
  await tutorial.getByRole("button", { name: "Close" }).click();

  await page.screenshot({ path: "artifacts/screenshots/web-blueprint-populated.png", fullPage: false });
});

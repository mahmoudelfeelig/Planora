import { expect, test } from "@playwright/test";

const publicRoutes = ["/", "/faq", "/privacy", "/login"];

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
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

test("public surfaces pass the release accessibility contract", async ({ page }, testInfo) => {
  for (const path of publicRoutes) {
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByRole("banner")).toBeVisible();
    await expect(page.getByRole("contentinfo")).toBeVisible();

    const findings = await page.evaluate(() => {
      const visible = (element: Element): element is HTMLElement => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
      };
      const unlabeledControls = [...document.querySelectorAll("button, input, select, textarea, a[href]")]
        .filter(visible)
        .filter((element) => {
          const html = element as HTMLElement;
          const label = html.getAttribute("aria-label") || html.getAttribute("title") || html.textContent?.trim();
          const labelledBy = html.getAttribute("aria-labelledby");
          if (element instanceof HTMLInputElement) {
            return !label && !labelledBy && !element.closest("label") &&
              !document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
          }
          return !label && !labelledBy;
        })
        .map((element) => element.outerHTML.slice(0, 180));
      const missingAlt = [...document.querySelectorAll("img")]
        .filter(visible)
        .filter((image) => !image.hasAttribute("alt"))
        .map((image) => image.outerHTML.slice(0, 180));
      const rgb = (value: string): [number, number, number, number] | null => {
        const match = value.match(/rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)(?:[, /]+([\d.]+))?\)/);
        if (!match) return null;
        return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])];
      };
      const luminance = ([red, green, blue]: [number, number, number]) => {
        const channels = [red, green, blue].map((channel) => {
          const normalized = channel / 255;
          return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
        });
        return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
      };
      const effectiveBackground = (element: Element): [number, number, number] => {
        let current: Element | null = element;
        while (current) {
          const color = rgb(getComputedStyle(current).backgroundColor);
          if (color && color[3] >= 0.95) return [color[0], color[1], color[2]];
          current = current.parentElement;
        }
        return [255, 255, 255];
      };
      const contrastFailures = [...document.querySelectorAll("body *")]
        .filter(visible)
        .filter((element) => [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()))
        .flatMap((element) => {
          const style = getComputedStyle(element);
          const foreground = rgb(style.color);
          if (!foreground || foreground[3] < 0.95) return [];
          const background = effectiveBackground(element);
          const first = luminance([foreground[0], foreground[1], foreground[2]]);
          const second = luminance(background);
          const ratio = (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
          const fontSize = Number.parseFloat(style.fontSize);
          const fontWeight = Number.parseInt(style.fontWeight, 10) || 400;
          const large = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
          return ratio + 0.01 < (large ? 3 : 4.5)
            ? [`${element.tagName.toLowerCase()}.${(element as HTMLElement).className}: ${ratio.toFixed(2)}`]
            : [];
        });
      return {
        contrastFailures,
        h1Count: document.querySelectorAll("h1").length,
        missingAlt,
        unlabeledControls,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });

    expect(findings.h1Count, `${path} should expose one primary heading`).toBe(1);
    expect(findings.missingAlt, `${path} images need alt text`).toEqual([]);
    expect(findings.unlabeledControls, `${path} controls need accessible names`).toEqual([]);
    expect(findings.contrastFailures, `${path} text must meet WCAG AA contrast`).toEqual([]);
    expect(findings.overflow, `${path} must not overflow horizontally`).toBeLessThanOrEqual(0);

    await page.keyboard.press("Tab");
    const focus = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      if (!active || active === document.body) return { visible: false, tag: "body" };
      const style = getComputedStyle(active);
      return {
        visible: style.outlineStyle !== "none" || style.boxShadow !== "none",
        tag: active.tagName.toLowerCase(),
      };
    });
    expect(focus.tag, `${path} should have a keyboard focus target`).not.toBe("body");
    expect(focus.visible, `${path} focus must be visibly indicated`).toBe(true);

    await page.screenshot({
      path: testInfo.outputPath(`${path === "/" ? "home" : path.slice(1)}.png`),
      fullPage: true,
    });
  }
});

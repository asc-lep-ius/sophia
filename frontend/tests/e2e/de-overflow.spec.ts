import { expect, test, type Page } from "@playwright/test";

import {
  authenticateShell,
  openCommandPaletteFromKeyboard,
} from "./shell-auth";

const routes = [
  "/app/study",
  "/app/study/1/predict",
  "/app/study/1/act",
  "/app/study/1/reflect",
  "/app/dashboard",
  "/app/login",
  "/app/settings",
];

test.use({
  locale: "de-DE",
  viewport: { height: 720, width: 320 },
});

for (const route of routes) {
  test(`${route} keeps German text inside the 320px viewport`, async ({
    page,
  }) => {
    if (route !== "/app/login") {
      await authenticateShell(page);
    }
    await page.setExtraHTTPHeaders({
      "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    });
    await page.goto(route);
    await expect(page.locator("html")).toHaveAttribute("lang", "de");

    const overflow = await page.evaluate(() => {
      const viewportWidth = document.documentElement.clientWidth;
      const offenders = Array.from(document.querySelectorAll("body *"))
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            className: element.className.toString(),
            tagName: element.tagName.toLowerCase(),
            width: rect.width,
            x: rect.x,
          };
        })
        .filter(
          (entry) =>
            entry.width > 0 &&
            (entry.x < -1 || entry.x + entry.width > viewportWidth + 1),
        );

      return {
        offenders,
        pageWidth: document.documentElement.scrollWidth,
        viewportWidth,
      };
    });

    expect(overflow.pageWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
    expect(overflow.offenders).toEqual([]);
  });
}

test("a revealed German study card fits the 320px viewport", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.setExtraHTTPHeaders({
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
  });
  await page.goto("/app/study/402/act");
  await page.getByLabel("Deine Antwort").fill("Eine Antwort zum Aufdecken.");
  await page.getByRole("button", { name: "Aufdecken" }).click();
  await expect(page.getByText("Was du geschrieben hast")).toBeVisible();

  await expectNoHorizontalOverflow(page);
});

test("expanded German mobile drawer fits the 320px viewport", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.setExtraHTTPHeaders({
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
  });
  await page.goto("/app/dashboard");
  await page.getByRole("button", { name: "Navigation oeffnen" }).click();
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible();

  await expectNoHorizontalOverflow(page);
});

test("expanded German command palette fits the 320px viewport", async ({
  page,
}) => {
  await authenticateShell(page);
  await page.setExtraHTTPHeaders({
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
  });
  await page.goto("/app/dashboard");
  await openCommandPaletteFromKeyboard(page, /Suche/);
  await expect(
    page.getByRole("dialog", { name: "Befehlspalette" }),
  ).toBeVisible();

  await expectNoHorizontalOverflow(page);
});

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const offenders = Array.from(document.querySelectorAll("body *"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          className: element.className.toString(),
          tagName: element.tagName.toLowerCase(),
          width: rect.width,
          x: rect.x,
        };
      })
      .filter(
        (entry) =>
          entry.width > 0 &&
          (entry.x < -1 || entry.x + entry.width > viewportWidth + 1),
      );

    return {
      offenders,
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth,
    };
  });

  expect(overflow.pageWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
  expect(overflow.offenders).toEqual([]);
}

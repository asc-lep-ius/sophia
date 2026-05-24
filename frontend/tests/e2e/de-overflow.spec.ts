import { expect, test } from "@playwright/test";

const routes = ["/app/study", "/app/dashboard", "/app/login", "/app/settings"];

test.use({
  locale: "de-DE",
  viewport: { height: 720, width: 320 },
});

for (const route of routes) {
  test(`${route} keeps German text inside the 320px viewport`, async ({
    page,
  }) => {
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

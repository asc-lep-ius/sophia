import { expect, test, type Page } from "@playwright/test";

import { authenticateShell } from "./shell-auth";

/**
 * The five #101 surfaces, each exercised three ways: the path a learner takes,
 * the path where the upstream call fails, and the same page on a phone.
 *
 * The failures are induced with a cookie. The frontend forwards the browser's
 * cookie header to the API verbatim, so it is the only channel this file has
 * into the fixture process; `failUpstream` names the path fragment to refuse.
 */

const PHONE = { width: 375, height: 667 };
const NARROW = { width: 320, height: 667 };
const PREVIEW_ORIGIN = "http://127.0.0.1:4173";

async function failUpstream(page: Page, pathFragment: string): Promise<void> {
  await page
    .context()
    .addCookies([
      { name: "sophia-e2e-fail", value: pathFragment, url: PREVIEW_ORIGIN },
    ]);
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => ({
    pageWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));

  expect(overflow.pageWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
}

test.describe("search", () => {
  /**
   * The acceptance criterion, measured rather than asserted about: typing a
   * word quickly has to reach the server once, and the results have to arrive
   * over a plain request instead of a stream.
   */
  test("typing quickly makes one request, and no stream is opened", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/search");

    const searchRequests: string[] = [];
    const streams: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (url.includes("/api/search")) {
        searchRequests.push(url);
      }
      if (request.resourceType() === "eventsource" || url.startsWith("ws")) {
        streams.push(url);
      }
    });

    const box = page.getByLabel("Search your course material");
    for (const chunk of ["gr", "gra", "grap", "graph", "graphe", "graphen"]) {
      await box.fill(chunk);
      await page.waitForTimeout(40);
    }

    await expect(page.getByText("Graphen und Suchverfahren")).toBeVisible();
    expect(searchRequests).toHaveLength(1);
    expect(streams).toEqual([]);
  });

  test("a submitted query is answered before the page hydrates", async ({
    browser,
  }) => {
    // No JavaScript at all: the GET form has to reach the server load, which
    // is what makes a search a shareable URL rather than a client-side state.
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await authenticateShell(page);
    await page.goto("/app/search?q=graph");

    await expect(page.getByText("Graphen und Suchverfahren")).toBeVisible();
    await context.close();
  });

  test("a search that finds nothing says so, naming the query", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/search?q=nichts");

    await expect(page.getByRole("status").first()).toContainText("nichts");
    await expect(page.getByText("Graphen und Suchverfahren")).toHaveCount(0);
  });

  test("a search the API refuses is reported as a failure", async ({
    page,
  }) => {
    await authenticateShell(page);
    await failUpstream(page, "/api/search");
    await page.goto("/app/search?q=graph");

    await expect(page.getByText(/did not answer/).first()).toBeVisible();
  });

  test("the search form and its results fit a phone", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await authenticateShell(page);
    await page.goto("/app/search?q=graph");

    await expect(page.getByText("Graphen und Suchverfahren")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test("a passage opens a retrieval prompt that refuses an empty answer", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/search?q=graph");

    await page
      .getByRole("button", { name: "Read the passage" })
      .first()
      .click();
    await expect(page.getByText("Retrieval practice")).toBeVisible();

    await page.getByRole("button", { name: "Save and continue" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "Write something before continuing",
    );

    await page.getByLabel("Your answer").fill("Knoten und Kanten.");
    await page.getByRole("button", { name: "Save and continue" }).click();
    await expect(page.getByText("Retrieval practice")).toHaveCount(0);
  });
});

test.describe("chronos", () => {
  test("deadlines carry a relative phrase and the UTC instant behind it", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/chronos");

    await expect(page.getByText("Overdue by 2 days")).toBeVisible();
    await expect(page.getByText("Due today")).toBeVisible();
    await expect(page.getByText("Due in 5 days")).toBeVisible();
    await expect(page.getByText(/UTC/).first()).toBeVisible();
  });

  test("the deadline list survives the workload panel failing", async ({
    page,
  }) => {
    await authenticateShell(page);
    await failUpstream(page, "/api/deadlines/workload");
    await page.goto("/app/chronos");

    await expect(page.getByText("Due today")).toBeVisible();
    const workload = page.getByRole("region", { name: "Workload" });
    await expect(workload.getByRole("status")).toContainText("did not answer");
  });

  test("a failed deadline list says so rather than showing an empty one", async ({
    page,
  }) => {
    await authenticateShell(page);
    await failUpstream(page, "/api/deadlines");
    await page.goto("/app/chronos");

    const upcoming = page.getByRole("region", { name: "Upcoming" });
    await expect(upcoming.getByRole("status")).toContainText("did not answer");
    await expect(upcoming.getByText("No deadlines synced")).toHaveCount(0);
  });

  test("syncing works through a plain form post", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await authenticateShell(page);
    await page.goto("/app/chronos");

    await page.getByRole("button", { name: "Sync deadlines" }).first().click();
    await expect(page.getByRole("status").first()).toContainText("synced");
    await context.close();
  });

  test("the deadline list fits the narrowest supported width", async ({
    page,
  }) => {
    await page.setViewportSize(NARROW);
    await authenticateShell(page);
    await page.goto("/app/chronos");

    await expect(page.getByText("Due today")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});

test.describe("chronos history", () => {
  test("a reflected deadline reads on time and an unreflected one missed", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/chronos/history");

    const history = page.getByRole("region", { name: "History" });
    await expect(history.getByText("On time")).toBeVisible();
    await expect(history.getByText("Missed")).toBeVisible();
    await expect(history.getByText(/cannot appear here/)).toBeVisible();
  });

  test("the outcome filter is a URL the server applies", async ({
    browser,
  }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await authenticateShell(page);
    await page.goto("/app/chronos/history");

    await page.getByLabel("Outcome").selectOption("missed");
    await page.getByRole("button", { name: "Apply" }).click();

    await expect(page).toHaveURL(/outcome=missed/);
    const history = page.getByRole("region", { name: "History" });
    await expect(history.getByText("Missed")).toBeVisible();
    await expect(history.getByText("On time")).toHaveCount(0);
    await context.close();
  });

  test("a failed history call says so rather than showing no history", async ({
    page,
  }) => {
    await authenticateShell(page);
    await failUpstream(page, "/api/deadline-history");
    await page.goto("/app/chronos/history");

    const history = page.getByRole("region", { name: "History" });
    await expect(history.getByRole("status")).toContainText("did not answer");
  });

  test("the history and its figure fit a phone", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await authenticateShell(page);
    await page.goto("/app/chronos/history");

    await expect(page.getByText("On time")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});

test.describe("calibration", () => {
  /**
   * The #97 defect made visible. The fixture carries one row the retired
   * scorer touched, and the page has to keep it out of the figure and say so
   * rather than averaging a manufactured perfect score into the picture.
   */
  test("a retired-scorer row is declared, not drawn", async ({ page }) => {
    await authenticateShell(page);
    await page.goto("/app/calibration");

    const measured = page.getByRole("region", {
      name: "Predicted against measured",
    });
    await expect(measured.getByText("Graphs")).toBeVisible();
    await expect(measured.getByText("Hashing")).toHaveCount(0);
    await expect(page.getByText(/retired scorer/)).toBeVisible();
    await expect(page.getByText(/no measurement yet/)).toBeVisible();
  });

  test("a reading from two topics says how thin it is", async ({ page }) => {
    await authenticateShell(page);
    await page.goto("/app/calibration");

    await expect(
      page.getByText(/too few to read a pattern from/),
    ).toBeVisible();
  });

  test("a failed calibration call says so rather than showing no data", async ({
    page,
  }) => {
    await authenticateShell(page);
    await failUpstream(page, "/api/calibration/ratings");
    await page.goto("/app/calibration");

    const measured = page.getByRole("region", {
      name: "Predicted against measured",
    });
    await expect(measured.getByRole("status")).toContainText("did not answer");
  });

  test("the figure and its table fit a phone", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await authenticateShell(page);
    await page.goto("/app/calibration");

    await expect(page.getByText("Graphs").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});

test.describe("register", () => {
  test("opening a course shows its groups and its registration window", async ({
    browser,
  }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await authenticateShell(page);
    await page.goto("/app/register");

    await page.getByRole("button", { name: "Open this course" }).click();

    await expect(page).toHaveURL(/course=123\.ABC/);
    await expect(page.getByText("Gruppe A")).toBeVisible();
    await expect(page.getByText(/Opens in/)).toBeVisible();
    await context.close();
  });

  test("only an open group offers a registration, and TISS decides the rest", async ({
    browser,
  }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await authenticateShell(page);
    await page.goto("/app/register?course=123.ABC");

    const buttons = page.getByRole("button", { name: /^Register for/ });
    await expect(buttons).toHaveCount(1);
    await buttons.click();

    await expect(page.getByRole("status")).toContainText(
      "Platz in Gruppe A erhalten",
    );
    await context.close();
  });

  test("a course TISS cannot answer for is reported, not left blank", async ({
    page,
  }) => {
    await authenticateShell(page);
    await failUpstream(page, "/targets/");
    await page.goto("/app/register?course=123.ABC");

    await expect(
      page.getByText(/did not answer for this course/),
    ).toBeVisible();
  });

  test("an unreachable TISS is reported on the favourites panel", async ({
    page,
  }) => {
    await authenticateShell(page);
    await failUpstream(page, "/registration/favorites");
    await page.goto("/app/register");

    const favourites = page.getByRole("region", { name: "Favourites" });
    await expect(favourites.getByRole("status")).toContainText(
      "did not answer",
    );
  });

  test("the groups table fits a phone", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await authenticateShell(page);
    await page.goto("/app/register?course=123.ABC");

    await expect(page.getByText("Gruppe A").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});

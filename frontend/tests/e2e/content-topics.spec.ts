import { expect, test, type Page } from "@playwright/test";

import { authenticateShell } from "./shell-auth";

/**
 * The three things #100 asks for, exercised the way a learner would hit them.
 *
 * The upload suite runs with JavaScript switched off. That is not a corner
 * case here — it is the acceptance criterion: the base workflow has to reach
 * the form action through a plain browser form post, with no client code in
 * the way at all.
 */

const PHONE = { width: 375, height: 667 };
const NARROW = { width: 320, height: 667 };

const PDF_FILE = {
  buffer: Buffer.from("%PDF-1.7\nAn uploaded lecture.\n"),
  mimeType: "application/pdf",
  name: "vorlesung-01.pdf",
};

test.describe("lecture upload without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("a plain multipart form post is accepted", async ({ page }) => {
    await authenticateShell(page);
    await page.goto("/app/content/sources");

    await page.getByLabel("Title").fill("Graph algorithms");
    await page.getByLabel("File").setInputFiles(PDF_FILE);
    await page.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByRole("status")).toContainText("Graph algorithms");
    // Queued, not finished: the processing that follows must not be implied by
    // the upload having been accepted.
    await expect(page.getByText(/queued for transcription/)).toBeVisible();
  });

  test("a file the allowlist does not cover comes back as a validation error", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/content/sources");

    await page.getByLabel("Title").fill("Payload");
    await page.getByLabel("File").setInputFiles({
      // Built from bytes rather than from a string literal: a NUL in the
      // source would make this file binary to git and to every diff tool.
      buffer: Buffer.from([0x4d, 0x5a, 0x90, 0x00, 0x6e, 0x6f, 0x70, 0x65]),
      mimeType: "application/pdf",
      name: "payload.exe",
    });
    await page.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByRole("alert")).toContainText(
      "That file type is not accepted",
    );
    // The title survives the refusal; the file input cannot be refilled by a
    // page, which is why only one of the two comes back.
    await expect(page.getByLabel("Title")).toHaveValue("Payload");
  });

  test("bytes that contradict the extension are refused by the server", async ({
    page,
  }) => {
    // The allowlist case above never reaches the API — the action's own
    // pre-check catches it. This one has to travel, because only the server
    // sees the bytes.
    await authenticateShell(page);
    await page.goto("/app/content/sources");

    await page.getByLabel("Title").fill("Disguised");
    await page.getByLabel("File").setInputFiles({
      buffer: Buffer.from([0x4d, 0x5a, 0x90, 0x00, 0x6e, 0x6f, 0x70, 0x65]),
      mimeType: "application/pdf",
      name: "vorlesung-02.pdf",
    });
    await page.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByRole("alert")).toContainText(
      "do not match its extension",
    );
  });

  test("the filters still reach the list with no client code", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/topics");

    await page.getByLabel("Came from").selectOption("manual");
    await page.getByRole("button", { name: "Apply" }).click();

    await expect(page).toHaveURL(/origin=manual/);
    await expect(page.getByRole("region", { name: "Topics" })).toContainText(
      "Dynamische Programmierungsaufgaben",
    );
  });
});

test.describe("topic filters on a phone", () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test("filters sit in a drawer and update the list without overflow", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/topics");

    // Closed to start with, so a filter set never pushes the list it filters
    // off the first screen.
    await expect(page.getByLabel("Came from")).toBeHidden();

    // Exact: "Clear filters" also contains "Filters", and it only fails to
    // match today because it sits inside a `display: none` panel.
    await page.getByRole("button", { name: "Filters", exact: true }).click();
    await expect(page.getByLabel("Came from")).toBeVisible();
    await expectNoHorizontalOverflow(page);

    await page.getByLabel("Came from").selectOption("quiz");
    await page.getByRole("button", { name: "Apply" }).click();

    const topics = page.getByRole("region", { name: "Topics" });
    await expect(topics).toContainText("Sorting");
    await expect(topics).not.toContainText("Graphs");
    await expectNoHorizontalOverflow(page);

    // The drawer closes on apply, and the filter is in the URL rather than in
    // a store — so reload and the back button both agree with the list.
    await expect(page).toHaveURL(/origin=quiz/);
    await expect(page).not.toHaveURL(/filters=open/);
  });

  test("the drawer survives a reload at the narrowest supported width", async ({
    page,
  }) => {
    await page.setViewportSize(NARROW);
    await authenticateShell(page);
    await page.goto("/app/topics?filters=open&origin=manual");

    await expect(page.getByLabel("Came from")).toBeVisible();
    await expect(page.getByLabel("Came from")).toHaveValue("manual");
    await expectNoHorizontalOverflow(page);
  });
});

test.describe("content language", () => {
  test("defaults to the course language while the chrome stays English", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/content");

    const notice = page.getByRole("complementary", {
      name: "Languages on this page",
    });
    await expect(notice).toContainText("Deutsch");
    await expect(notice).toContainText("English");
    await expect(notice).toContainText("language the course is examined in");
    // The chrome is the UI locale's, not the course's.
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(
      page.getByRole("heading", { level: 1, name: "Lectures" }),
    ).toBeVisible();
  });

  test("an explicit choice survives a hop between the content surfaces", async ({
    page,
  }) => {
    await authenticateShell(page);
    await page.goto("/app/content?lang=en");

    await page
      .getByRole("button", { name: "Add or sync lectures" })
      .first()
      .click();

    await expect(page).toHaveURL(/\/app\/content\/sources\?lang=en/);
    await expect(
      page.getByRole("complementary", { name: "Languages on this page" }),
    ).toContainText("chose this content language");
  });
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

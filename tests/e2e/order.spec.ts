import { expect, test } from "@playwright/test"

import {
  ORDER_ID,
  RESULT,
  ResumableServer,
  config,
  fakeFile,
  mockConfig,
  mockOrder,
  mockOrderAction,
  mockUploads,
  order,
  orderPath,
  serveOrderShell,
} from "./support/mock-api"

// docs/UX.md §6 items 1, 6, 7 and every status of the order page table (§2).
const HTTP_NOT_FOUND = 404

test.beforeEach(async ({ page }) => {
  await serveOrderShell(page)
})

test("happy path with payments off: form, upload 3 files, stages, result, Copy", async ({ page, context, browserName }) => {
  test.skip(browserName !== "chromium", "clipboard permissions are Chromium-only")
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
  await mockConfig(page, config({ payments: "off" }))
  await page.route("**/api/checkout", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ order_url: orderPath() }) })
  )
  const orders = await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
  await mockUploads(page, new ResumableServer())
  const starts: string[] = []
  await page.route(`**/api/orders/${ORDER_ID}/start`, (route) => {
    // The status moves on only once Start reached the API, as it does for real; `queued` spans
    // more than one poll so the test does not race the 1 s poll interval.
    starts.push(route.request().method())
    orders.replace([
      order({ status: "queued", queue_position: 1 }),
      order({ status: "queued", queue_position: 1 }),
      order({ status: "running", stage: { name: "planning", elapsed_s: 120 }, stages_done: ["reading"] }),
      order({ status: "done", result: RESULT }),
    ])
    return route.fulfill({ contentType: "application/json", body: "null" })
  })
  await mockOrderAction(page, "viewed")

  await page.goto("/new")
  await page.getByRole("radio", { name: /Recipe/ }).click()
  await expect(page.getByRole("radio", { name: "30 s" })).toBeChecked()
  await page.getByRole("button", { name: "Continue" }).click()

  await expect(page.getByRole("heading", { name: "Add your clips and photos" })).toBeVisible()
  await page.getByLabel("Choose files").setInputFiles([fakeFile("a.mp4", 300), fakeFile("b.mov", 300, "video/quicktime"), fakeFile("c.jpg", 50, "image/jpeg")])
  await expect(page.getByText("done", { exact: true })).toHaveCount(3)

  await page.getByRole("button", { name: "Start editing" }).click()
  await expect.poll(() => starts.length).toBe(1)
  await expect(page.getByText("1 Reel ahead of you.")).toBeVisible()
  await expect(page.getByRole("list", { name: "Progress" }).getByText("Planning the edit")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Your Reel is ready" })).toBeVisible()
  await expect(page.getByTestId("player-text")).toBeVisible()
  await expect(page.getByTestId("player-clean")).toBeVisible()

  await page.getByRole("button", { name: "Copy" }).click()
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(RESULT.caption)
})

test("a wrong token shows the link-doesn't-work page and no order data", async ({ page }) => {
  await mockConfig(page)
  await mockOrder(page, order(), { status: HTTP_NOT_FOUND })
  await page.goto(orderPath(ORDER_ID, "wrong"))
  await expect(page.getByText("This link doesn't work. Use the link in the email we sent you.")).toBeVisible()
  await expect(page.getByText("Add your clips and photos")).toHaveCount(0)
})

test("a link without a token never asks the API", async ({ page }) => {
  await mockConfig(page)
  const orders = await mockOrder(page, order())
  await page.goto(`/o/${ORDER_ID}`)
  await expect(page.getByText("This link doesn't work. Use the link in the email we sent you.")).toBeVisible()
  expect(orders.headers).toHaveLength(0)
})

test("?t= from Stripe moves behind # and is sent as X-Order-Token", async ({ page }) => {
  await mockConfig(page)
  const orders = await mockOrder(page, order({ status: "queued", queue_position: 2 }))
  await page.goto(`/o/${ORDER_ID}?t=from-stripe`)
  await expect(page.getByText("2 Reels ahead of you.")).toBeVisible()
  expect(new URL(page.url()).search).toBe("")
  expect(new URL(page.url()).hash).toBe("#t=from-stripe")
  expect(orders.headers[0]).toBe("from-stripe")
})

test("Delete my files: inline confirm, status becomes deleted, players disappear", async ({ page }) => {
  await mockConfig(page)
  const orders = await mockOrder(page, order({ status: "done", result: RESULT }))
  await mockOrderAction(page, "viewed")
  const deletes = await mockOrderAction(page, "files")
  await page.goto(orderPath())
  await page.getByRole("button", { name: "Delete my files now" }).click()
  await expect(page.getByText("Delete the Reels and your clips? This can't be undone.")).toBeVisible()
  await page.getByRole("button", { name: "Keep" }).click()
  await expect(page.getByText("Delete the Reels and your clips?")).toHaveCount(0)

  await page.getByRole("button", { name: "Delete my files now" }).click()
  orders.replace([order({ status: "deleted" })])
  await page.getByRole("button", { name: "Delete", exact: true }).click()
  await expect(page.getByText("Your files are deleted.")).toBeVisible()
  await expect(page.getByTestId("player-text")).toHaveCount(0)
  expect(deletes.map((hit) => hit.method)).toEqual(["DELETE"])
})

const STATES = [
  { view: order({ status: "awaiting_payment" }), words: ["Confirming your code…"] },
  { view: order({ status: "queued", queue_position: 1 }), words: ["Waiting for a free editor.", "1 Reel ahead of you.", "You can close this page. We'll email k•••@gmail.com when it's ready."] },
  { view: order({ status: "paused" }), words: ["We hit this month's budget. Your Reel is saved and starts when it resets. We'll email you."] },
  { view: order({ status: "expired" }), words: ["This checkout expired before it was confirmed.", "Start again"] },
  { view: order({ status: "abandoned" }), words: ["This order was never started, so its clips were deleted.", "Start again"] },
  { view: order({ status: "deleted" }), words: ["Your files are deleted."] },
  { view: order({ status: "failed", error: { code: "cost_cap" } }), words: ["This one needed more editing than our $5 limit allows. Try again with fewer or shorter clips.", "Kevin has been notified.", "Try with fewer clips"] },
  { view: order({ status: "failed", error: { code: "render_error" } }), words: ["Something broke while cutting. Kevin has been notified.", "Start again"] },
]

for (const { view, words } of STATES) {
  test(`status ${view.status}${view.error ? ` (${view.error.code})` : ""} shows its words`, async ({ page }) => {
    await mockConfig(page)
    await mockOrder(page, view)
    const fulfils = await mockOrderAction(page, "fulfil")
    await page.goto(orderPath())
    for (const text of words) await expect(page.getByText(text, { exact: true }).first()).toBeVisible()
    if (view.status === "awaiting_payment") await expect.poll(() => fulfils.length).toBe(1)
  })
}

test("running shows real stages: done ticked, current with minutes, listening only with voice", async ({ page }) => {
  await mockConfig(page)
  await mockOrder(page, order({ status: "running", stage: { name: "rendering", elapsed_s: 200 }, stages_done: ["reading", "planning"] }))
  await page.goto(orderPath())
  await expect(page.getByRole("list", { name: "Progress" }).getByText("Cutting and colour")).toBeVisible()
  // The live region announces only the current stage, once.
  await expect(page.locator("[aria-live=polite]")).toHaveText("Cutting and colour")
  await expect(page.getByText("3 min")).toBeVisible()
  await expect(page.locator("[aria-current=step]")).toContainText("Cutting and colour")
  await expect(page.getByText("Listening")).toHaveCount(0)
  await expect(page.getByText("Improving the cut")).toHaveCount(0)
})

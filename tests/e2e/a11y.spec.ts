import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Page } from "@playwright/test"

import { RESULT, fakeFile, mockConfig, mockOrder, mockOrderAction, mockUploads, order, orderPath, ResumableServer, serveOrderShell } from "./support/mock-api"
import type { OrderView } from "../../web/src/lib/types"

// docs/UX.md §6 item 8: axe-core finds no serious or critical violations in any state.
const BLOCKING = new Set(["serious", "critical"])

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).analyze()
  const blocking = results.violations.filter((v) => BLOCKING.has(v.impact ?? ""))
  expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([])
}

test.beforeEach(async ({ page }) => {
  // Reduced motion turns colour transitions off (global.css), so axe never samples a half-way colour.
  await page.emulateMedia({ reducedMotion: "reduce" })
  await mockConfig(page)
  await serveOrderShell(page)
})

for (const path of ["/", "/privacy", "/new", "/does-not-exist"]) {
  test(`page ${path}`, async ({ page }) => {
    await page.goto(path)
    await page.waitForLoadState("networkidle")
    await expectAccessible(page)
  })
}

test("/new with an error shown", async ({ page }) => {
  await page.route("**/api/checkout", (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "week_full" }) }))
  await page.goto("/new")
  await page.getByRole("radio", { name: /Recipe/ }).click()
  await page.getByLabel("Invite code").fill("CODE")
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByRole("alert")).toBeVisible()
  await expectAccessible(page)
})

test("order page while uploading files", async ({ page }) => {
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
  await mockUploads(page, new ResumableServer())
  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles(fakeFile("a.mp4", 10))
  await expect(page.getByText("done", { exact: true })).toBeVisible()
  await expectAccessible(page)
})

const VIEWS: OrderView[] = [
  order({ status: "queued", queue_position: 1 }),
  order({ status: "running", stage: { name: "planning", elapsed_s: 90 }, stages_done: ["reading"] }),
  order({ status: "done", result: RESULT }),
  order({ status: "failed", error: { code: "render_error" } }),
  order({ status: "expired" }),
]

for (const view of VIEWS) {
  test(`order status ${view.status}`, async ({ page }) => {
    await mockOrder(page, view)
    await mockOrderAction(page, "viewed")
    await page.goto(orderPath())
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
    await expectAccessible(page)
  })
}

test("bad link", async ({ page }) => {
  await mockOrder(page, order(), { status: 404 })
  await page.goto(orderPath())
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
  await expectAccessible(page)
})

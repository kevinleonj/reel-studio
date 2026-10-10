import { expect, test } from "@playwright/test"

import { LINK_CODE, ORDER_ID, mockConfig, mockOrder, order, serveOrderShell } from "./support/mock-api"
import type { OrderView } from "../../web/src/lib/types"

// Senior review C1 and W7: the token never rides along as Referer, and data newer than this
// build never leaves an empty page.

test("landing on ?t= sends the token in no Referer header", async ({ page }) => {
  const referers: string[] = []
  page.on("request", (request) => {
    const referer = request.headers()["referer"]
    if (referer !== undefined) referers.push(referer)
  })
  await mockConfig(page)
  await serveOrderShell(page)
  await mockOrder(page, order({ status: "queued", queue_position: 1 }))
  await page.goto(`/o/${ORDER_ID}?t=${LINK_CODE}`)
  await expect(page.getByRole("heading", { name: "Waiting for a free editor." })).toBeVisible()
  await page.waitForLoadState("networkidle")
  expect(referers.filter((value) => value.includes(LINK_CODE))).toEqual([])
})

test("an unknown failure code falls back to a known message", async ({ page }) => {
  await mockConfig(page)
  await serveOrderShell(page)
  const view = { ...order({ status: "failed" }), error: { code: "provider_overloaded" } } as unknown as OrderView
  await mockOrder(page, view)
  await page.goto(`/o/${ORDER_ID}#t=${LINK_CODE}`)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Something broke while cutting. Kevin has been notified.")
})

test("an unknown status shows a neutral line, not an empty page", async ({ page }) => {
  await mockConfig(page)
  await serveOrderShell(page)
  await mockOrder(page, { ...order(), status: "archived" } as unknown as OrderView)
  await page.goto(`/o/${ORDER_ID}#t=${LINK_CODE}`)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Loading…")
})

test("a malformed order id shows the bad-link page", async ({ page }) => {
  await mockConfig(page)
  await serveOrderShell(page)
  await page.goto(`/o/%zz#t=${LINK_CODE}`)
  await expect(page.getByText("This link doesn't work. Use the link in the email we sent you.")).toBeVisible()
})

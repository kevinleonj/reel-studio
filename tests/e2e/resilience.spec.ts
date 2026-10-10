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
import type { OrderView } from "../../web/src/lib/types"

// Pins the fixes from the senior reviews (W1-W11, N1-N3): each case fails when its fix is removed.
const KIB = 1024
const HEADING_UPLOAD = "Add your clips and photos"

test.beforeEach(async ({ page }) => {
  await serveOrderShell(page)
})

test("N1: a poll answered after Start never brings the upload panel back", async ({ page }) => {
  await mockConfig(page)
  await mockOrderAction(page, "files", { files: [{ name: "a.mp4", size: 10 }] })
  let started = false
  let gets = 0
  await page.route(`**/api/orders/${ORDER_ID}`, async (route) => {
    gets += 1
    const view = started ? order({ status: "queued", queue_position: 1 }) : order()
    if (!started && gets > 1) await new Promise((resolve) => setTimeout(resolve, 1500)) // stale poll in flight
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(view) })
  })
  await page.route(`**/api/orders/${ORDER_ID}/start`, (route) => {
    started = true
    return route.fulfill({ contentType: "application/json", body: "null" })
  })
  // Record every change of the page's <h1>: a flash back to the upload panel is the bug, even if
  // the next poll hides it again.
  await page.addInitScript(() => {
    const seen: string[] = []
    Object.assign(window, { h1History: seen })
    new MutationObserver(() => {
      const text = document.querySelector("h1")?.textContent ?? ""
      if (seen[seen.length - 1] !== text) seen.push(text)
    }).observe(document, { subtree: true, childList: true, characterData: true })
  })
  await page.goto(orderPath())
  await expect(page.getByRole("button", { name: "Start editing" })).toBeEnabled()
  await expect.poll(() => gets).toBeGreaterThan(1) // a slow poll is now pending
  await page.getByRole("button", { name: "Start editing" }).click()
  await expect(page.getByRole("heading", { name: "Waiting for a free editor." })).toBeVisible()
  await page.waitForTimeout(2000) // the stale poll answers in this window
  const history = await page.evaluate(() => (window as unknown as { h1History: string[] }).h1History)
  const queuedAt = history.indexOf("Waiting for a free editor.")
  expect(queuedAt).toBeGreaterThanOrEqual(0)
  expect(history.slice(queuedAt)).not.toContain(HEADING_UPLOAD)
})

test("N2: a slow link that keeps bytes despite timeouts still finishes", async ({ page }) => {
  await mockConfig(page, config({ timeouts: { request_ms: 10_000, chunk_ms: 300 } }))
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
  await mockUploads(page, new ResumableServer({ stallAfterPersistMs: 600 }))
  await page.goto(orderPath())
  // 8 chunks, more than chunk_retries (5): every chunk times out, so only resetting the streak on
  // confirmed progress lets the file finish.
  await page.getByLabel("Choose files").setInputFiles(fakeFile("slow.mov", 8 * 256, "video/quicktime"))
  await expect(page.getByText("done", { exact: true })).toBeVisible({ timeout: 20_000 })
})

test("N3: an empty file is refused before any upload starts", async ({ page }) => {
  await mockConfig(page)
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
  const batches = await mockOrderAction(page, "uploads", { targets: [] })
  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles({ name: "IMG_0001.MOV", mimeType: "video/quicktime", buffer: Buffer.alloc(0) })
  await expect(page.getByRole("alert")).toHaveText("IMG_0001.MOV is empty. Choose it again from your gallery.")
  expect(batches).toHaveLength(0)
})

test("W1: a chunk size Cloud Storage would refuse shows the error line, not a broken page", async ({ page }) => {
  await mockConfig(page, config({ upload: { chunk_bytes: 1000, parallel_files: 2, chunk_retries: 5, backoff_ms: 10 } }))
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
  await page.goto(orderPath())
  await expect(page.getByRole("alert")).toHaveText("Something went wrong on this page. Reload to try again.")
})

test("W2: Retry on many failed files still uploads two at a time", async ({ page }) => {
  await mockConfig(page, config({ upload: { chunk_bytes: 256 * KIB, parallel_files: 2, chunk_retries: 1, backoff_ms: 10 } }))
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
  const server = new ResumableServer({ delayMs: 150 })
  server.down = true
  await mockUploads(page, server)
  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles([fakeFile("a.mp4", 300), fakeFile("b.mp4", 300), fakeFile("c.mp4", 300)])
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(3)
  server.down = false
  server.maxInFlightSessions = 0
  // Each click hides that row's button, so always press the first one left.
  for (let i = 0; i < 3; i += 1) await page.getByRole("button", { name: "Retry" }).first().click()
  await expect(page.getByText("done", { exact: true })).toHaveCount(3)
  expect(server.maxInFlightSessions).toBe(2)
})

test("W3: an API call that hangs ends with the network message", async ({ page }) => {
  await mockConfig(page, config({ timeouts: { request_ms: 500, chunk_ms: 10_000 } }))
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [{ name: "a.mp4", size: 10 }] })
  await page.route(`**/api/orders/${ORDER_ID}/start`, () => new Promise(() => undefined)) // never answers
  await page.goto(orderPath())
  await page.getByRole("button", { name: "Start editing" }).click()
  await expect(page.getByRole("alert")).toHaveText("We couldn't reach the server. Check your connection and try again.")
})

test("W5: the order page recovers when the API comes back", async ({ page }) => {
  await mockConfig(page)
  let gets = 0
  await page.route(`**/api/orders/${ORDER_ID}`, (route) => {
    gets += 1
    if (gets === 1) return route.fulfill({ status: 503, contentType: "application/json", body: "{}" })
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(order({ status: "queued", queue_position: 1 })) })
  })
  await page.goto(orderPath())
  await expect(page.getByText("We couldn't reach the server. Check your connection and try again.")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Waiting for a free editor." })).toBeVisible({ timeout: 10_000 })
})

test("W5: a failed /api/config is asked again, not cached", async ({ page }) => {
  let calls = 0
  await page.route("**/api/config", (route) => {
    calls += 1
    if (calls <= 2) return route.fulfill({ status: 500, contentType: "application/json", body: "{}" })
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(config()) })
  })
  await mockOrder(page, order({ status: "queued", queue_position: 1 }))
  await page.goto(orderPath())
  await expect(page.getByRole("heading", { name: "Waiting for a free editor." })).toBeVisible({ timeout: 10_000 })
  expect(calls).toBeGreaterThan(2)
})

test("W6: Stripe's Cancel refills the form; a failed release keeps the link", async ({ page }) => {
  await mockConfig(page)
  const settings = { style: "talking", length_s: 60, text_lang: "es", keep_voice: true, chips: ["Calm pace"], note: "Keep the pour." }
  await page.route(`**/api/orders/${ORDER_ID}/cancel`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ settings }) }))
  await page.goto(`/new?cancel=${ORDER_ID}&t=code`)
  await expect(page.getByRole("radio", { name: /Someone talking/ })).toBeChecked()
  await expect(page.getByRole("radio", { name: "60 s" })).toBeChecked()
  await expect(page.getByLabel("Anything we should know?")).toHaveValue("Keep the pour.")
  await expect(page.getByRole("button", { name: "Calm pace" })).toHaveAttribute("aria-pressed", "true")
  expect(new URL(page.url()).search).toBe("")

  await page.unroute(`**/api/orders/${ORDER_ID}/cancel`)
  await page.route(`**/api/orders/${ORDER_ID}/cancel`, (route) => route.fulfill({ status: 404, contentType: "application/json", body: "{}" }))
  await page.goto(`/new?cancel=${ORDER_ID}&t=code`)
  await expect(page.getByRole("radio", { name: /Recipe/ })).toBeVisible()
  expect(new URL(page.url()).searchParams.get("cancel")).toBe(ORDER_ID)
})

test("W8: Back from checkout gives a working Continue button again", async ({ page }) => {
  await mockConfig(page)
  await page.route("**/api/checkout", () => new Promise(() => undefined)) // the redirect never completes
  await page.goto("/new")
  await page.getByRole("radio", { name: /Recipe/ }).click()
  await page.getByLabel("Invite code").fill("CODE")
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByRole("button", { name: "Opening checkout…" })).toBeDisabled()
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })))
  await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled()
})

test("W9: Copy works outside a secure context and keeps focus on the button", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
  await page.addInitScript(() => Object.defineProperty(window, "isSecureContext", { get: () => false }))
  await mockConfig(page)
  await mockOrder(page, order({ status: "done", result: RESULT }))
  await mockOrderAction(page, "viewed")
  await page.goto(orderPath())
  await page.getByRole("button", { name: "Copy" }).click()
  await expect(page.getByRole("button", { name: "Copied" })).toBeFocused()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(RESULT.caption)
})

test("W10: files chosen before the listing arrives stay on the list", async ({ page }) => {
  await mockConfig(page)
  await mockOrder(page, order())
  await page.route(`**/api/orders/${ORDER_ID}/files`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ files: [{ name: "earlier.mp4", size: 100 }] }) })
  })
  await mockUploads(page, new ResumableServer())
  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles(fakeFile("now.mp4", 10))
  await expect(page.getByText("earlier.mp4")).toBeVisible({ timeout: 5000 })
  await expect(page.getByText("now.mp4")).toBeVisible()
})

test("W11: the delete confirm starts on Keep and Keep returns focus to the opener", async ({ page }) => {
  await mockConfig(page)
  await mockOrder(page, order({ status: "done", result: RESULT }))
  await mockOrderAction(page, "viewed")
  await page.goto(orderPath())
  await page.getByRole("button", { name: "Delete my files now" }).click()
  await expect(page.getByRole("button", { name: "Keep" })).toBeFocused()
  await page.getByRole("button", { name: "Keep" }).click()
  await expect(page.getByRole("button", { name: "Delete my files now" })).toBeFocused()
})

test("W11: the voice switch is a 44 px touch target", async ({ page }) => {
  await mockConfig(page)
  await page.goto("/new")
  const box = await page.getByRole("switch", { name: "Keep the voice?" }).boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)
  expect(box?.width).toBeGreaterThanOrEqual(44)
})

test("S6: an inherited key as failure code still falls back", async ({ page }) => {
  await mockConfig(page)
  await mockOrder(page, { ...order({ status: "failed" }), error: { code: "constructor" } } as unknown as OrderView)
  await page.goto(orderPath())
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Something broke while cutting. Kevin has been notified.")
})

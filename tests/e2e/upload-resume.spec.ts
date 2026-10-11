import { expect, test } from "@playwright/test"

import { ResumableServer, fakeFile, mockConfig, mockOrder, mockOrderAction, mockUploads, order, orderPath, serveOrderShell } from "./support/mock-api"

// docs/UX.md §6 item 2, the most likely failure: a chunk is dropped mid-file and the file still
// finishes by resuming from the server's offset, not from zero.
const CHUNK = 256 * 1024

test.beforeEach(async ({ page }) => {
  await mockConfig(page)
  await serveOrderShell(page)
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
})

test("a dropped chunk resumes from the server offset", async ({ page }) => {
  const server = new ResumableServer({ dropChunkAt: CHUNK }) // lose the answer to the second chunk
  await mockUploads(page, server)

  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles(fakeFile("pour.mp4", 700))

  await expect(page.getByText("done", { exact: true })).toBeVisible()
  expect(server.log.map((line) => line.split(" ").slice(1).join(" "))).toEqual([
    "bytes 0-262143/716800",
    "bytes 262144-524287/716800", // aborted
    "bytes */716800", // asks the session for its offset
    "bytes 524288-716799/716800", // resumes after the bytes the server already has
  ])
  await expect(page.getByRole("button", { name: "Start editing" })).toBeEnabled()
})

test("a chunk that keeps failing marks the file failed with Retry", async ({ page }) => {
  await page.route("**/api/orders/*/uploads", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ targets: [{ name: "a.mp4", upload_url: "/api/local-upload/x" }] }) })
  )
  await page.route("**/api/local-upload/**", (route) => route.abort("failed"))

  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles(fakeFile("a.mp4", 10))

  await expect(page.getByText("failed", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Start editing" })).toBeDisabled()
})

// STEP-07 review round 2: asking again for a name closes its older session on the server, so the
// page replaces that name's row instead of keeping a row whose upload can no longer finish.
test("choosing the same file again replaces its row", async ({ page }) => {
  let asked = 0
  await page.route("**/api/orders/*/uploads", (route) => {
    asked += 1
    const target = { name: "a.mp4", upload_url: `/api/local-upload/s${asked}` }
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ targets: [target] }) })
  })
  await page.route("**/api/local-upload/s1", (route) => route.abort("failed")) // the first never finishes
  await page.route("**/api/local-upload/s2", (route) => route.fulfill({ status: 200 }))

  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles(fakeFile("a.mp4", 10))
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible()
  await page.getByLabel("Choose files").setInputFiles(fakeFile("a.mp4", 10))

  await expect(page.getByText("done", { exact: true })).toBeVisible()
  await expect(page.getByText("a.mp4", { exact: true })).toHaveCount(1)
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Start editing" })).toBeEnabled()
})

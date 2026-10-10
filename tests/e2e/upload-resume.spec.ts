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

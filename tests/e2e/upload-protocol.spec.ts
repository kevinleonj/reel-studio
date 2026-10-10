import { expect, test } from "@playwright/test"

import { ResumableServer, config, fakeFile, mockConfig, mockOrder, mockOrderAction, mockUploads, order, orderPath, serveOrderShell } from "./support/mock-api"

// The parts of the resumable protocol a well-behaved mock would hide (senior review W1, W2, W4):
// the server may keep less than it was sent, may never advance, and only two files go at once.
const KIB = 1024
const CHUNK = 512 * KIB

test.beforeEach(async ({ page }) => {
  await serveOrderShell(page)
  await mockOrder(page, order())
  await mockOrderAction(page, "files", { files: [] })
})

test("when the session keeps only part of a chunk, the next chunk starts at its Range", async ({ page }) => {
  await mockConfig(page, config({ upload: { chunk_bytes: CHUNK, parallel_files: 2, chunk_retries: 5, backoff_ms: 10 } }))
  const server = new ResumableServer({ persistAtMost: 256 * KIB })
  await mockUploads(page, server)
  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles(fakeFile("long.mov", 1100, "video/quicktime"))
  await expect(page.getByText("done", { exact: true })).toBeVisible()
  const starts = server.log.map((line) => Number(/bytes (\d+)-/.exec(line)?.[1]))
  // 1,126,400 bytes; each non-final 512 KiB chunk keeps 256 KiB; from 786,432 the chunk is the last one.
  expect(starts).toEqual([0, 262144, 524288, 786432])
})

test("a session that never advances fails the file instead of looping", async ({ page }) => {
  await mockConfig(page)
  const server = new ResumableServer({ neverAdvance: true })
  await mockUploads(page, server)
  await page.goto(orderPath())
  await page.getByLabel("Choose files").setInputFiles(fakeFile("stuck.mp4", 600))
  await expect(page.getByText("failed", { exact: true })).toBeVisible()
  // 5 tries, each a chunk plus an offset query: bounded, not hundreds of PUTs.
  expect(server.log.length).toBeLessThanOrEqual(10)
})

test("two files at a time across separate picks", async ({ page }) => {
  await mockConfig(page)
  const server = new ResumableServer({ delayMs: 150 })
  await mockUploads(page, server)
  await page.goto(orderPath())
  const input = page.getByLabel("Choose files")
  await input.setInputFiles([fakeFile("a.mp4", 600), fakeFile("b.mp4", 600), fakeFile("c.mp4", 600)])
  await expect(page.getByText("uploading", { exact: false }).first()).toBeVisible()
  await input.setInputFiles([fakeFile("d.mp4", 600), fakeFile("e.mp4", 600)]) // second pick while the first runs
  await expect(page.getByText("done", { exact: true })).toHaveCount(5)
  expect(server.maxInFlightSessions).toBe(2)
})

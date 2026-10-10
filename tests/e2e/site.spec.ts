import { expect, test } from "@playwright/test"

import { RESULT, mockConfig, mockOrder, mockOrderAction, order, orderPath, serveOrderShell } from "./support/mock-api"

// Analytics off (STEP-06 task 5): no request to any Google host. Plus the search and link-preview
// rules of docs/UX.md §2 that the static build must carry.
const GOOGLE_HOST = /(^|\.)(google|googletagmanager|google-analytics|doubleclick|googleadservices|gstatic)\.[a-z.]+$/

test("analytics off: no page makes a request to a Google host", async ({ page }) => {
  const hosts: string[] = []
  page.on("request", (request) => hosts.push(new URL(request.url()).hostname))
  await mockConfig(page)
  await serveOrderShell(page)
  await mockOrder(page, order({ status: "done", result: RESULT }))
  await mockOrderAction(page, "viewed")
  for (const path of ["/", "/privacy", "/new", orderPath()]) {
    await page.goto(path)
    await page.waitForLoadState("networkidle")
  }
  expect(hosts.filter((host) => GOOGLE_HOST.test(host))).toEqual([])
  expect(await page.evaluate(() => (window as { dataLayer?: unknown[] }).dataLayer)).toBeUndefined()
})

test("landing: one h1, title, description, canonical, Open Graph, finished HTML", async ({ page, request }) => {
  const html = await (await request.get("/")).text()
  expect(html).toContain("Turn your food clips into a Reel that&#39;s ready to post.")
  expect(html).not.toContain("noindex")
  expect(html).not.toContain("googletagmanager")
  await mockConfig(page)
  await page.goto("/")
  await expect(page.locator("h1")).toHaveCount(1)
  await expect(page).toHaveTitle(/Reel Studio/)
  await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /40 clips/)
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/$/)
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", /\/og\.png$/)
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image")
  await expect(page.getByRole("link", { name: "Start a Reel" })).toHaveAttribute("href", "/new")
})

test("noindex on /new and the order shell; robots.txt allows all and names the sitemap", async ({ request }) => {
  for (const path of ["/new", "/o/"]) {
    expect(await (await request.get(path)).text()).toContain('<meta name="robots" content="noindex, nofollow"')
  }
  const robots = await (await request.get("/robots.txt")).text()
  expect(robots).toContain("Allow: /")
  expect(robots).toMatch(/Sitemap: https?:\/\/\S+\/sitemap-index\.xml/)
  expect(robots).not.toContain("Disallow")
  const sitemap = await (await request.get("/sitemap-0.xml")).text()
  expect(sitemap).not.toContain("/new")
  expect(sitemap).not.toContain("/o/")
})

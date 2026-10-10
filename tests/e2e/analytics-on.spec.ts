import { expect, test } from "@playwright/test"

import { LINK_CODE, ORDER_ID, config, mockConfig, mockOrder, order, orderPath, serveOrderShell } from "./support/mock-api"

// With analytics switched on (D75) but no consent yet: consent defaults come first, page_location
// is the route template, nothing reaches Google, and nothing carries the order id or the token.
const TAG_URL = "https://www.googletagmanager.com/gtag/js"
const ON = { enabled: true, ga4_id: "G-TEST000000", ads_id: "", tag_url: TAG_URL }
const GOOGLE_HOST = /(^|\.)(google|googletagmanager|google-analytics|doubleclick|googleadservices|gstatic)\.[a-z.]+$/

async function dataLayer(page: import("@playwright/test").Page): Promise<unknown[][] | undefined> {
  return page.evaluate(() => {
    const layer = (window as { dataLayer?: ArrayLike<unknown>[] }).dataLayer
    return layer?.map((entry) => Array.from(entry))
  })
}

test("enabled, before consent: defaults first, template location, no Google request, no id", async ({ page }) => {
  const hosts: string[] = []
  page.on("request", (request) => hosts.push(new URL(request.url()).hostname))
  await mockConfig(page, config({ analytics: ON }))
  await serveOrderShell(page)
  await mockOrder(page, order({ status: "queued", queue_position: 1 }))
  await page.goto(orderPath())
  await expect.poll(async () => (await dataLayer(page))?.length ?? 0).toBeGreaterThanOrEqual(3)
  const layer = (await dataLayer(page)) ?? []
  expect(layer[0]).toEqual([
    "consent",
    "default",
    { ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied", analytics_storage: "denied" },
  ])
  expect(layer[1]).toEqual(["set", { page_location: new URL("/o/:id", page.url()).href }])
  expect(layer).toContainEqual(["event", "page_view", { page_location: "/o/:id" }])
  const text = JSON.stringify(layer)
  expect(text).not.toContain(ORDER_ID)
  expect(text).not.toContain(LINK_CODE)
  expect(hosts.filter((host) => GOOGLE_HOST.test(host))).toEqual([])
})

test("a tag URL that is not https keeps analytics off", async ({ page }) => {
  await mockConfig(page, config({ analytics: { ...ON, tag_url: "http://example.test/gtag/js" } }))
  await page.goto("/")
  await page.waitForLoadState("networkidle")
  expect(await dataLayer(page)).toBeUndefined()
})

test("enabled without a measurement id stays off", async ({ page }) => {
  await mockConfig(page, config({ analytics: { ...ON, ga4_id: "" } }))
  await page.goto("/")
  await page.waitForLoadState("networkidle")
  expect(await dataLayer(page)).toBeUndefined()
})

test("the 404 page reports no page_view", async ({ page }) => {
  await mockConfig(page, config({ analytics: ON }))
  await page.goto("/does-not-exist")
  await page.waitForLoadState("networkidle")
  expect(JSON.stringify((await dataLayer(page)) ?? [])).not.toContain("page_view")
})

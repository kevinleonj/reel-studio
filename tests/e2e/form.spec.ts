import { expect, test, type Page } from "@playwright/test"

import { config, mockConfig } from "./support/mock-api"

// docs/UX.md §6 items 3, 4 and 5 on /new.
const HTTP_CONFLICT = 409
const HTTP_TOO_MANY = 429

const voice = (page: Page) => page.getByRole("switch", { name: "Keep the voice?" })

test("the note stops at 200 characters; Calm and Fast exclude each other", async ({ page }) => {
  await mockConfig(page)
  await page.goto("/new")
  const note = page.getByLabel("Anything we should know?")
  await note.fill("x".repeat(250))
  await expect(note).toHaveValue("x".repeat(200))
  await expect(page.getByText("200/200")).toBeVisible()

  const calm = page.getByRole("button", { name: "Calm pace" })
  const fast = page.getByRole("button", { name: "Fast pace" })
  await calm.click()
  await expect(calm).toHaveAttribute("aria-pressed", "true")
  await fast.click()
  await expect(fast).toHaveAttribute("aria-pressed", "true")
  await expect(calm).toHaveAttribute("aria-pressed", "false")
})

test("the voice toggle follows the style until touched, then never again", async ({ page }) => {
  await mockConfig(page)
  await page.goto("/new")
  await page.getByRole("radio", { name: /Quick clips, no talking/ }).click()
  await expect(voice(page)).not.toBeChecked()
  await page.getByRole("radio", { name: /Someone talking/ }).click()
  await expect(voice(page)).toBeChecked()

  await voice(page).click()
  await expect(voice(page)).not.toBeChecked()
  await page.getByRole("radio", { name: /One long video/ }).click()
  await expect(voice(page)).not.toBeChecked()
  await page.getByRole("radio", { name: /Quick clips, no talking/ }).click()
  await page.getByRole("radio", { name: /Tutorial/ }).click()
  await expect(voice(page)).not.toBeChecked()
})

test("without a Gemini key the voice toggle is off and explains why", async ({ page }) => {
  await mockConfig(page, config({ voice_available: false }))
  await page.goto("/new")
  await page.getByRole("radio", { name: /Someone talking/ }).click()
  await expect(voice(page)).toBeDisabled()
  await expect(voice(page)).not.toBeChecked()
  await expect(page.getByText("Needs a Gemini key on this server")).toBeVisible()
})

const ERRORS = [
  { code: "week_full", status: HTTP_CONFLICT, message: "This week's Reels are all taken. Places free up on Monday." },
  { code: "code_invalid", status: HTTP_CONFLICT, message: "This code doesn't work. Check it, or ask Kevin for a new one." },
  { code: "rate_limited", status: HTTP_TOO_MANY, message: "Too many tries. Wait a minute and try again." },
]

for (const { code, status, message } of ERRORS) {
  test(`${code} shows its message and keeps the form values`, async ({ page }) => {
    await mockConfig(page)
    await page.route("**/api/checkout", (route) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ error: code }) })
    )
    await page.goto("/new")
    const continueButton = page.getByRole("button", { name: "Continue" })
    await expect(continueButton).toBeDisabled()
    await page.getByRole("radio", { name: /Recipe/ }).click()
    await page.getByRole("radio", { name: "60 s" }).click()
    await page.getByLabel("Anything we should know?").fill("Keep the pour.")
    await page.getByLabel("Invite code").fill("FRIEND-1")
    await continueButton.click()

    await expect(page.getByRole("alert")).toHaveText(message)
    await expect(page.getByLabel("Invite code")).toHaveValue("FRIEND-1")
    await expect(page.getByLabel("Anything we should know?")).toHaveValue("Keep the pour.")
    await expect(page.getByRole("radio", { name: /Recipe/ })).toBeChecked()
    await expect(page.getByRole("radio", { name: "60 s" })).toBeChecked()
  })
}

test("with payments off the code is hidden and the email is optional", async ({ page }) => {
  await mockConfig(page, config({ payments: "off" }))
  let sent: unknown = null
  await page.route("**/api/checkout", (route) => {
    sent = route.request().postDataJSON()
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ order_url: "/o/abc#t=xyz" }) })
  })
  await page.goto("/new")
  await expect(page.getByLabel("Invite code")).toHaveCount(0)
  await expect(page.getByText("Optional: we email you when it's ready.")).toBeVisible()
  await page.getByRole("radio", { name: /Recipe/ }).click()
  await page.getByRole("button", { name: "Continue" }).click()
  await page.waitForURL(/\/o\/abc/)
  expect(sent).toMatchObject({ settings: { style: "recipe", length_s: 30, keep_voice: false }, code: "" })
})

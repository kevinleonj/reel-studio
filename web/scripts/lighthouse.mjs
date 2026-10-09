// Speed budget on the built site (docs/UX.md §4), run by `make prerelease`: Lighthouse's default
// (mobile) profile against `astro preview`. Largest Contentful Paint ≤ 2.5 s and Cumulative Layout
// Shift ≤ 0.1 as written; Interaction to Next Paint has no lab measurement, so Total Blocking Time
// ≤ 200 ms stands in for it (Lighthouse's documented lab proxy for INP).
// Chromium comes from Playwright (already pinned) over its debugging port, so no chrome-launcher.
import { spawn } from "node:child_process"
import { setTimeout as sleep } from "node:timers/promises"

import { chromium } from "@playwright/test"
import lighthouse from "lighthouse"

const PORT = 4331
const DEBUG_PORT = 9333
const BASE = `http://localhost:${PORT}` // hardcode-ok: the preview server this script starts
const PAGES = ["/", "/privacy", "/new"]
const READY_TIMEOUT_MS = 60_000
const POLL_MS = 500
const BUDGET = {
  "largest-contentful-paint": 2500, // ms
  "cumulative-layout-shift": 0.1,
  "total-blocking-time": 200, // ms, lab proxy for INP ≤ 200 ms
}

async function waitFor(url) {
  const deadline = Date.now() + READY_TIMEOUT_MS
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(POLL_MS * 4) })).ok) return
    } catch {
      // not listening yet
    }
    await sleep(POLL_MS)
  }
  throw new Error(`preview server not ready at ${url}`)
}

const preview = spawn("npx", ["astro", "preview", "--port", String(PORT), "--ignore-lock"], { stdio: "ignore" })
let failed = false
try {
  await waitFor(BASE)
  const browser = await chromium.launch({ args: [`--remote-debugging-port=${DEBUG_PORT}`] })
  try {
    for (const page of PAGES) {
      const result = await lighthouse(`${BASE}${page}`, { port: DEBUG_PORT, onlyCategories: ["performance"], logLevel: "error" })
      const lines = Object.entries(BUDGET).map(([audit, limit]) => {
        const value = result.lhr.audits[audit].numericValue
        const ok = value <= limit
        failed ||= !ok
        return `${ok ? "ok  " : "FAIL"} ${page} ${audit} ${value.toFixed(audit === "cumulative-layout-shift" ? 3 : 0)} (budget ${limit})`
      })
      console.log(lines.join("\n"))
    }
  } finally {
    await browser.close()
  }
} finally {
  preview.kill()
}
process.exit(failed ? 1 : 0)

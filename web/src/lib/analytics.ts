import type { AppConfig } from "./types"

// Analytics seam (D75, docs/UX.md §5). Off unless /api/config says enabled. When enabled:
// Consent Mode v2 defaults (all four types denied) run before anything else, and the Google tag
// script loads only after grantConsent() (basic mode, F70). The consent banner comes later.
// Never sent: order id, token, email, real /o/ path. The tag script URL arrives with the IDs in
// /api/config (`analytics.tag_url`), so no Google host is written in web code.
const TRANSACTION_ID_HEX = 16 // characters of the SHA-256 hex digest (docs/UX.md §5)
const HEX_RADIX = 16

type Params = Record<string, string | number>

export interface AnalyticsEvents {
  page_view: { page_location: "/" | "/new" | "/o/:id" | "/privacy" }
  generate_lead: { style: string; length: number }
  begin_checkout: { value: number; currency: string }
  purchase: { transaction_id: string; value: number; currency: string }
  upload_complete: { file_count: number; total_mb: number }
  reel_ready: { style: string; duration_s: number }
  reel_download: { version: "text" | "clean" }
  feedback_sent: { rating: number }
}

declare global {
  interface Window {
    dataLayer?: unknown[]
  }
}

let settings: AppConfig["analytics"] | null = null
let tagLoaded = false

// gtag.js reads the `arguments` object itself, not an array (Google tag snippet), hence no rest
// parameter; the overload keeps call sites typed.
function gtag(...args: unknown[]): void
function gtag(): void {
  window.dataLayer = window.dataLayer ?? []
  // eslint-disable-next-line prefer-rest-params -- gtag.js needs the real Arguments object
  window.dataLayer.push(arguments)
}

/**
 * `route` is the page's template ("/o/:id"). gtag's page_location defaults to location.href
 * (only the fragment dropped), which would carry the real order id, so it is pinned to
 * origin + template for every hit, before anything else is queued.
 */
export function initAnalytics(config: AppConfig["analytics"], route: AnalyticsEvents["page_view"]["page_location"]): void {
  if (!config.enabled) {
    settings = config
    return
  }
  if (config.ga4_id === "") throw new Error("analytics.enabled without ga4_id")
  const tagUrl = new URL(config.tag_url) // throws on an empty or malformed tag_url: analytics stays off
  if (tagUrl.protocol !== "https:") throw new Error("analytics.tag_url must be https")
  gtag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    analytics_storage: "denied",
  })
  gtag("set", { page_location: new URL(route, window.location.origin).href })
  settings = { ...config, tag_url: tagUrl.toString() }
}

/** Called by the consent banner's "Accept" (not built yet). */
export function grantConsent(): void {
  if (!settings?.enabled || tagLoaded) return
  const src = new URL(settings.tag_url)
  src.searchParams.set("id", settings.ga4_id)
  tagLoaded = true
  gtag("consent", "update", {
    ad_storage: "granted",
    ad_user_data: "granted",
    ad_personalization: "granted",
    analytics_storage: "granted",
  })
  const script = document.createElement("script")
  script.async = true
  script.src = src.toString()
  document.head.append(script)
  gtag("js", new Date())
  gtag("config", settings.ga4_id, { send_page_view: false })
  if (settings.ads_id) gtag("config", settings.ads_id)
}

export function track<E extends keyof AnalyticsEvents>(event: E, params: AnalyticsEvents[E]): void {
  if (!settings?.enabled) return
  gtag("event", event, params as Params)
}

/** transaction_id = first 16 hex characters of SHA-256(order id); the id itself is never sent. */
export async function transactionId(orderId: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(orderId))
  return Array.from(new Uint8Array(digest), (b) => b.toString(HEX_RADIX).padStart(2, "0"))
    .join("")
    .slice(0, TRANSACTION_ID_HEX)
}

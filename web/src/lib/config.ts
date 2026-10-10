import { api, setRequestTimeout } from "./api"
import { initAnalytics, track, type AnalyticsEvents } from "./analytics"
import type { AppConfig } from "./types"

// One /api/config request per page, shared by the page script and the island. The answer is
// checked once here; a failed or invalid answer is not cached, so the next caller tries again.
let pending: Promise<AppConfig> | null = null

/** Values the page divides by or loops on: zero or missing would hang or spin the page. */
function checkConfig(config: AppConfig): AppConfig {
  const positive: [string, unknown][] = [
    ["poll_seconds", config.poll_seconds],
    ["upload.parallel_files", config.upload?.parallel_files],
    ["upload.chunk_bytes", config.upload?.chunk_bytes],
    ["timeouts.request_ms", config.timeouts?.request_ms],
    ["timeouts.chunk_ms", config.timeouts?.chunk_ms],
  ]
  for (const [name, value] of positive) {
    if (typeof value !== "number" || !(value > 0)) throw new Error(`/api/config ${name} must be a positive number`)
  }
  return config
}

export function loadConfig(): Promise<AppConfig> {
  pending =
    pending ??
    api
      .config()
      .then((config) => {
        checkConfig(config)
        setRequestTimeout(config.timeouts.request_ms)
        return config
      })
      .catch((error: unknown) => {
        pending = null
        throw error
      })
  return pending
}

type Route = AnalyticsEvents["page_view"]["page_location"]
const ROUTES: readonly Route[] = ["/", "/new", "/o/:id", "/privacy"]

function isRoute(value: string): value is Route {
  return ROUTES.some((route) => route === value)
}

/** page_view with the route template, never the real /o/ path or the #t= token (docs/UX.md §5). */
export async function startPageAnalytics(): Promise<void> {
  const route = document.body.dataset.route
  if (route === undefined) return // the 404 page reports nothing
  if (!isRoute(route)) {
    console.error("page has an unknown data-route; page_view skipped", { route })
    return
  }
  let config: AppConfig
  try {
    config = await loadConfig()
  } catch (error) {
    console.error("could not load /api/config; analytics stays off", { error: String(error) })
    return
  }
  try {
    initAnalytics(config.analytics, route)
    track("page_view", { page_location: route })
  } catch (error) {
    console.error("analytics settings in /api/config are invalid; analytics stays off", { error: String(error) })
  }
}

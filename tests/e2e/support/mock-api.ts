import type { Page, Route } from "@playwright/test"

import type { AppConfig, OrderView } from "../../../web/src/lib/types"

// Stand-in for reel-api so the UI can be tested with no backend. Shapes follow
// web/src/lib/types.ts, the contract the API must implement (STEP-06 tasks 1–2).
const KIB = 1024
const HTTP_OK = 200
const HTTP_BAD_REQUEST = 400
const HTTP_RESUME_INCOMPLETE = 308

export const ORDER_ID = "0123456789abcdef0123456789abcdef" // hardcode-ok: fixture order id (32 hex, docs/ARCHITECTURE.md §4), not a secret
/** The fixture order link's access code (the part after #t=). */
export const LINK_CODE = "fixture-link-code"
export const orderPath = (id = ORDER_ID, code = LINK_CODE) => `/o/${id}#t=${code}`

export function config(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    payments: "stripe",
    voice_available: true,
    styles: [
      { key: "montage", voice_default: false },
      { key: "recipe", voice_default: false },
      { key: "long_take", voice_default: true },
      { key: "talking", voice_default: true },
      { key: "tutorial", voice_default: true },
    ],
    chips: {
      items: ["Start with the finished dish", "Calm pace", "Fast pace", "Show every step", "No text over faces", "End on the first bite"],
      exclusive: [["Calm pace", "Fast pace"]],
    },
    lengths_s: [15, 30, 60, 90],
    default_length_s: 30,
    text_languages: ["en", "es"],
    note_max_chars: 200,
    limits: { max_files: 40, max_total_bytes: 4_000_000_000, max_file_minutes: 20, allowed_types: ["video/mp4", "video/quicktime", "image/jpeg", "image/png"] },
    upload: { chunk_bytes: 256 * KIB, parallel_files: 2, chunk_retries: 5, backoff_ms: 10 },
    timeouts: { request_ms: 10_000, chunk_ms: 10_000 },
    poll_seconds: 1,
    feedback: { rating_max: 5, comment_max_chars: 1000 },
    price: { value: 19, currency: "EUR" },
    analytics: { enabled: false, ga4_id: "", ads_id: "", tag_url: "" },
    ...overrides,
  }
}

export function order(overrides: Partial<OrderView> = {}): OrderView {
  return {
    status: "paid",
    settings: { style: "recipe", length_s: 30, text_lang: "en", keep_voice: false, chips: [], note: "" },
    email_hint: "k•••@gmail.com",
    queue_position: null,
    stage: null,
    stages_done: [],
    result: null,
    error: null,
    feedback_sent: false,
    ...overrides,
  }
}

export const RESULT: NonNullable<OrderView["result"]> = {
  versions: [
    { kind: "clean", play_url: "/media/clean.mp4", download_url: "/media/clean.mp4?dl=1" },
    { kind: "text", play_url: "/media/text.mp4", download_url: "/media/text.mp4?dl=1" },
  ],
  duration_s: 30,
  caption: "Grandma's pistachio cheesecake, start to finish. #recipe",
  text_lines: [{ at_s: 0, text: "Pistachio cheesecake" }, { at_s: 12.5, text: "Pour the sauce" }],
  music: { mood: "warm", tempo: "slow" },
  left_out: [{ file: "IMG_0003.MOV", reason: "Blurred from start to end." }],
  wishes: [{ wish: "Calm pace", applied: true, reason: "Long holds on the pour." }],
  doubts: ["The first shot is a little dark."],
}

const json = (route: Route, body: unknown, status = HTTP_OK) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })

export async function mockConfig(page: Page, value: AppConfig = config()): Promise<void> {
  await page.route("**/api/config", (route) => json(route, value))
}

/** The API serves o/index.html for every /o/<id>; astro preview only serves /o/, so map it here. */
export async function serveOrderShell(page: Page): Promise<void> {
  await page.route(/\/o\/[^/?#]+(\?.*)?$/, async (route) => {
    const shell = await route.fetch({ url: new URL("/o/", route.request().url()).toString() })
    await route.fulfill({ response: shell })
  })
}

/** Answers GET /api/orders/<id> from a list of views; each GET advances one step until the last. */
export async function mockOrder(page: Page, views: OrderView[] | OrderView, options: { status?: number } = {}) {
  const steps = Array.isArray(views) ? [...views] : [views]
  const headers: string[] = []
  await page.route(`**/api/orders/${ORDER_ID}`, (route) => {
    headers.push(route.request().headers()["x-order-token"] ?? "")
    if (options.status !== undefined) return json(route, { error: "not_found" }, options.status)
    const view = steps.length > 1 ? steps.shift() : steps[0]
    return json(route, view)
  })
  return { headers, replace: (next: OrderView[]) => steps.splice(0, steps.length, ...next) }
}

/** Mocks /api/orders/<id>/<action> (any method); returns the requests it saw. */
export async function mockOrderAction(page: Page, action: string, body: unknown = null, status = HTTP_OK) {
  const hits: { method: string; body: unknown }[] = []
  await page.route(`**/api/orders/${ORDER_ID}/${action}`, (route) => {
    const raw = route.request().postData()
    hits.push({ method: route.request().method(), body: raw ? JSON.parse(raw) : null })
    return json(route, body, status)
  })
  return hits
}

export interface ServerModes {
  /** Lose the answer to the chunk starting at this offset, once per session (bytes persisted). */
  dropChunkAt?: number | null
  /** Persist at most this many bytes of each chunk, as Cloud Storage may (it reports less in Range). */
  persistAtMost?: number
  /** Answer every chunk with 308 and no Range header: the session never advances. */
  neverAdvance?: boolean
  /** Hold every answer this long, so concurrent uploads overlap. */
  delayMs?: number
  /** Keep each chunk at once, then answer this late: a slow link whose client may time out. */
  stallAfterPersistMs?: number
}

/**
 * A resumable-upload session store speaking the Cloud Storage protocol: `bytes a-b/total` chunks
 * answer 308 + Range until complete (200); `bytes * /total` reports the offset.
 */
export class ResumableServer {
  readonly offsets = new Map<string, number>()
  readonly log: string[] = []
  maxInFlightSessions = 0
  /** While true every request is dropped (a dead network); flip it to recover. */
  down = false
  private readonly active = new Map<string, number>()
  private readonly dropped = new Set<string>()

  constructor(private readonly modes: ServerModes = {}) {}

  async install(page: Page): Promise<void> {
    await page.route("**/api/local-upload/**", (route) => this.handle(route))
  }

  private async handle(route: Route) {
    const session = new URL(route.request().url()).pathname
    this.active.set(session, (this.active.get(session) ?? 0) + 1)
    this.maxInFlightSessions = Math.max(this.maxInFlightSessions, this.active.size)
    try {
      if (this.down) return await route.abort("failed")
      if (this.modes.delayMs) await new Promise((resolve) => setTimeout(resolve, this.modes.delayMs))
      return await this.answer(route, session)
    } finally {
      const left = (this.active.get(session) ?? 1) - 1
      if (left === 0) this.active.delete(session)
      else this.active.set(session, left)
    }
  }

  private async answer(route: Route, session: string) {
    const range = route.request().headers()["content-range"] ?? ""
    this.log.push(`${session} ${range}`)
    const offset = this.offsets.get(session) ?? 0
    const probe = /^bytes \*\/(\d+)$/.exec(range)
    const chunk = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(range)
    if (chunk) {
      const [start, end, total] = chunk.slice(1).map(Number)
      if (this.modes.neverAdvance) return route.fulfill({ status: HTTP_RESUME_INCOMPLETE })
      if (start === this.modes.dropChunkAt && !this.dropped.has(session)) {
        this.dropped.add(session)
        this.offsets.set(session, end + 1) // the bytes arrived, the answer is lost
        return route.abort("failed")
      }
      const last = end + 1 >= total
      const kept = this.modes.persistAtMost !== undefined && !last ? Math.min(end + 1, start + this.modes.persistAtMost) : end + 1
      const next = start === offset ? kept : offset
      this.offsets.set(session, next)
      if (this.modes.stallAfterPersistMs) {
        await new Promise((resolve) => setTimeout(resolve, this.modes.stallAfterPersistMs))
        // The client may have timed out and gone; answering a closed request is not an error here.
        return (next >= total ? route.fulfill({ status: HTTP_OK }) : this.incomplete(route, next)).catch(() => undefined)
      }
      return next >= total ? route.fulfill({ status: HTTP_OK }) : this.incomplete(route, next)
    }
    if (probe) return offset >= Number(probe[1]) ? route.fulfill({ status: HTTP_OK }) : this.incomplete(route, offset)
    return route.fulfill({ status: HTTP_BAD_REQUEST })
  }

  private incomplete(route: Route, next: number) {
    const headers: Record<string, string> = next > 0 ? { Range: `bytes=0-${next - 1}` } : {}
    return route.fulfill({ status: HTTP_RESUME_INCOMPLETE, headers })
  }
}

export async function mockUploads(page: Page, server: ResumableServer) {
  await server.install(page)
  await page.route(`**/api/orders/${ORDER_ID}/uploads`, (route) => {
    const files = (JSON.parse(route.request().postData() ?? "{}") as { files: { name: string }[] }).files
    return json(route, { targets: files.map((f, i) => ({ name: f.name, upload_url: `/api/local-upload/s${i}-${encodeURIComponent(f.name)}` })) })
  })
}

export function fakeFile(name: string, kib: number, mimeType = "video/mp4") {
  return { name, mimeType, buffer: Buffer.alloc(kib * KIB, 1) }
}

// The JSON contract between this web app and reel-api (docs/ARCHITECTURE.md §7).
// Phase A defines it here; the API (STEP-06 tasks 1–2) must return exactly these shapes,
// and tests/e2e/support/mock-api.ts mirrors them.

export type Payments = "off" | "stripe"

export interface StyleOption {
  key: string
  voice_default: boolean
}

export interface AppConfig {
  payments: Payments
  voice_available: boolean
  styles: StyleOption[]
  chips: { items: string[]; exclusive: string[][] }
  lengths_s: number[]
  default_length_s: number
  text_languages: string[]
  note_max_chars: number
  limits: { max_files: number; max_total_bytes: number; max_file_minutes: number; allowed_types: string[] }
  /** chunk_bytes must be a multiple of 256 KiB (F307). */
  upload: { chunk_bytes: number; parallel_files: number; chunk_retries: number; backoff_ms: number }
  /**
   * Per-request limits: API calls and each upload chunk (a stalled request counts as failed).
   * chunk_ms must cover one full chunk on the slowest uplink we support: 8 MiB at 1 Mbit/s is
   * about 67 s, so the API should send at least 90 000.
   */
  timeouts: { request_ms: number; chunk_ms: number }
  poll_seconds: number
  feedback: { rating_max: number; comment_max_chars: number }
  price: { value: number; currency: string } | null
  /** tag_url: the Google tag script (gtag/js) without the id; empty while disabled. */
  analytics: { enabled: boolean; ga4_id: string; ads_id: string; tag_url: string }
}

export interface OrderSettings {
  style: string
  length_s: number
  text_lang: string
  keep_voice: boolean
  chips: string[]
  note: string
}

export type CheckoutError = "code_invalid" | "code_inactive" | "week_full" | "rate_limited"
export type UploadError = "too_many_files" | "too_large" | "bad_type" | "no_files"

/** `checkout_url` with PAYMENTS=stripe, `order_url` (`/o/<id>#t=<token>`) with PAYMENTS=off. */
export interface CheckoutResponse {
  checkout_url?: string
  order_url?: string
}

export type OrderStatus =
  | "awaiting_payment"
  | "paid"
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "paused"
  | "expired"
  | "abandoned"
  | "deleted"

export type StageKey = "reading" | "listening" | "planning" | "rendering" | "checking" | "revising" | "saving"

export type FailureCode =
  | "no_usable_input"
  | "model_refusal"
  | "cost_cap"
  | "output_too_long"
  | "provider_unavailable"
  | "render_error"
  | "job_killed"

export interface ReelVersion {
  kind: "text" | "clean"
  play_url: string
  download_url: string
}

export interface OrderResult {
  versions: ReelVersion[]
  duration_s: number
  caption: string
  text_lines: { at_s: number; text: string }[]
  music: { mood: string; tempo: string }
  left_out: { file: string; reason: string }[]
  wishes: { wish: string; applied: boolean; reason: string }[]
  doubts: string[]
}

export interface OrderView {
  status: OrderStatus
  settings: OrderSettings
  /** Masked by the API (k•••@gmail.com); the full address never reaches the page. */
  email_hint: string | null
  queue_position: number | null
  stage: { name: StageKey; elapsed_s: number } | null
  stages_done: StageKey[]
  result: OrderResult | null
  error: { code: FailureCode } | null
  feedback_sent: boolean
}

export interface UploadTarget {
  name: string
  upload_url: string
}

export interface FinishedFile {
  name: string
  size: number
}

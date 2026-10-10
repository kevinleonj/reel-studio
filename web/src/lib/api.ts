import type { AppConfig, CheckoutResponse, FinishedFile, OrderSettings, OrderView, UploadTarget } from "./types"

// Same-origin client for reel-api (docs/ARCHITECTURE.md §7). Errors arrive as {"error": "<code>"}.
const TOKEN_HEADER = "X-Order-Token" // hardcode-ok: header name from docs/ARCHITECTURE.md §7, not a secret
const JSON_TYPE = "application/json"
// Until /api/config answers there is no configured limit; this one covers that first request.
const BOOTSTRAP_TIMEOUT_MS = 15_000
let requestTimeoutMs = BOOTSTRAP_TIMEOUT_MS

/** Applies `timeouts.request_ms` from /api/config to every later call. */
export function setRequestTimeout(ms: number): void {
  requestTimeoutMs = ms
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string | null
  /** The file a `bad_type` answer refers to ({"error": "bad_type", "file": "<name>"}). */
  readonly file: string | null

  constructor(status: number, code: string | null, file: string | null = null) {
    super(code ?? `HTTP ${status}`)
    this.status = status
    this.code = code
    this.file = file
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE"
  body?: unknown
  token?: string
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const payload: unknown = await response.json()
    if (payload !== null && typeof payload === "object" && "error" in payload && typeof payload.error === "string") {
      const file = "file" in payload && typeof payload.file === "string" ? payload.file : null
      return new ApiError(response.status, payload.error, file)
    }
  } catch (error) {
    console.warn("error body is not JSON", { status: response.status, error: String(error) })
  }
  return new ApiError(response.status, null)
}

async function request<T>(path: string, { method = "GET", body, token }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers["Content-Type"] = JSON_TYPE
  if (token !== undefined) headers[TOKEN_HEADER] = token
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(requestTimeoutMs),
  })
  if (!response.ok) throw await toError(response)
  const text = await response.text()
  return (text === "" ? null : JSON.parse(text)) as T
}

const order = (id: string) => `/api/orders/${encodeURIComponent(id)}`

export const api = {
  config: () => request<AppConfig>("/api/config"),
  checkout: (settings: OrderSettings, code: string, email: string) =>
    request<CheckoutResponse>("/api/checkout", { method: "POST", body: { settings, code, email } }),
  getOrder: (id: string, token: string) => request<OrderView>(order(id), { token }),
  fulfil: (id: string, token: string) => request<null>(`${order(id)}/fulfil`, { method: "POST", token }),
  cancel: (id: string, token: string) =>
    request<{ settings: OrderSettings }>(`${order(id)}/cancel`, { method: "POST", token }),
  createUploads: (id: string, token: string, files: { name: string; size: number; type: string }[]) =>
    request<{ targets: UploadTarget[] }>(`${order(id)}/uploads`, { method: "POST", token, body: { files } }),
  listFiles: (id: string, token: string) => request<{ files: FinishedFile[] }>(`${order(id)}/files`, { token }),
  start: (id: string, token: string) => request<null>(`${order(id)}/start`, { method: "POST", token }),
  viewed: (id: string, token: string) => request<null>(`${order(id)}/viewed`, { method: "POST", token }),
  feedback: (id: string, token: string, rating: number, comment: string) =>
    request<null>(`${order(id)}/feedback`, { method: "POST", token, body: { rating, comment } }),
  deleteFiles: (id: string, token: string) => request<null>(`${order(id)}/files`, { method: "DELETE", token }),
}

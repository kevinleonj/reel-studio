import { useCallback, useEffect, useRef, useState } from "react"

import { ErrorBoundary } from "@/components/ErrorBoundary"
import { track, transactionId } from "@/lib/analytics"
import { ApiError, api } from "@/lib/api"
import { loadConfig } from "@/lib/config"
import { copy } from "@/lib/copy"
import { usePolling } from "@/lib/poll"
import { orderIdFromPath, takeToken } from "@/lib/token"
import type { AppConfig, OrderStatus, OrderView } from "@/lib/types"
import { Result } from "./Result"
import { Failed, Message, Queued, Running } from "./StatusViews"
import { UploadPanel } from "./UploadPanel"

// /o/<order_id>#t=<token>: one page driven by `status` (docs/UX.md §2).
const t = copy.order
// `paid` is polled too: after Start the page must move on even if one GET fails.
const POLLED: OrderStatus[] = ["awaiting_payment", "paid", "queued", "running"]
const HTTP_NOT_FOUND = 404
const RETRY_SECONDS_BEFORE_CONFIG = 5

type Load = { kind: "loading" } | { kind: "bad" } | { kind: "error" } | { kind: "ready"; config: AppConfig; order: OrderView }

/** null = a transient failure: keep what is shown (a poll that fails must not blank the page). */
async function fetchOrder(id: string, token: string): Promise<Load | null> {
  try {
    const [config, order] = await Promise.all([loadConfig(), api.getOrder(id, token)])
    return { kind: "ready", config, order }
  } catch (error) {
    // Same 404 for a wrong id or a wrong token (docs/ARCHITECTURE.md §7).
    if (error instanceof ApiError && error.status === HTTP_NOT_FOUND) return { kind: "bad" }
    console.error("could not load the order", { error: String(error) })
    return null
  }
}

const settle = (next: Load | null) => (current: Load): Load =>
  next ?? (current.kind === "ready" ? current : { kind: "error" })

function OrderPageInner() {
  const [id] = useState(orderIdFromPath)
  const [token] = useState(takeToken)
  const [state, setState] = useState<Load>(id && token ? { kind: "loading" } : { kind: "bad" })
  const seen = useRef(new Set<OrderStatus>())
  const latest = useRef(0)

  // Newest request wins: a poll sent before Start must not overwrite the answer that follows it.
  const load = useCallback(async (): Promise<Load | null | undefined> => {
    if (!id || !token) return undefined
    latest.current += 1
    const mine = latest.current
    const next = await fetchOrder(id, token)
    return mine === latest.current ? next : undefined
  }, [id, token])

  const refresh = useCallback(async () => {
    const next = await load()
    if (next !== undefined) setState(settle(next))
  }, [load])

  useEffect(() => {
    void load().then((next) => {
      if (next !== undefined) setState(settle(next))
    })
  }, [load])

  const status = state.kind === "ready" ? state.order.status : null
  const polling = state.kind === "error" || (status !== null && POLLED.includes(status))
  const seconds = state.kind === "ready" ? state.config.poll_seconds : RETRY_SECONDS_BEFORE_CONFIG
  usePolling(() => void refresh(), seconds, polling)

  // One-time effects the first time this page sees a status.
  useEffect(() => {
    if (state.kind !== "ready" || !id || !token || seen.current.has(state.order.status)) return
    const { config, order } = state
    seen.current.add(order.status)
    if (order.status === "awaiting_payment") {
      api
        .fulfil(id, token)
        .then(refresh)
        .catch((error: unknown) => console.error("fulfil failed", { error: String(error) }))
    }
    if (order.status === "paid" && config.price !== null) {
      const price = config.price
      transactionId(id)
        .then((tx) => track("purchase", { transaction_id: tx, value: price.value, currency: price.currency }))
        .catch((error: unknown) => console.error("purchase event skipped", { error: String(error) }))
    }
    if (order.status === "done" && order.result !== null) {
      track("reel_ready", { style: order.settings.style, duration_s: order.result.duration_s })
      api.viewed(id, token).catch((error: unknown) => console.error("viewed failed", { error: String(error) }))
    }
  }, [state, id, token, refresh])

  return (
    <div className="flex flex-col gap-6">
      {/* Only a short status line is announced, not every progress update on the page. */}
      <p className="sr-only" aria-live="polite">
        {announcement(state)}
      </p>
      <StateView state={state} id={id ?? ""} token={token ?? ""} refresh={refresh} />
    </div>
  )
}

export function OrderPage() {
  return (
    <ErrorBoundary>
      <OrderPageInner />
    </ErrorBoundary>
  )
}

function announcement(state: Load): string {
  if (state.kind !== "ready") return ""
  const { order } = state
  if (order.status === "running" && order.stage !== null) return t.stages[order.stage.name]
  if (order.status === "queued") return t.queued.waiting
  if (order.status === "done") return copy.result.heading
  return ""
}

interface StateViewProps {
  state: Load
  id: string
  token: string
  refresh: () => Promise<void>
}

function StateView({ state, id, token, refresh }: StateViewProps) {
  if (state.kind === "loading") return <p className="text-muted-foreground">{copy.site.loading}</p>
  if (state.kind === "bad") return <Message text={t.badLink} />
  if (state.kind === "error") return <Message text={copy.form.errors.network} />
  const { config, order } = state
  switch (order.status) {
    case "awaiting_payment":
      return <Message text={t.awaitingPayment} />
    case "paid":
      return <UploadPanel id={id} token={token} config={config} onStarted={() => void refresh()} />
    case "queued":
      return <Queued order={order} />
    case "running":
      return <Running order={order} />
    case "done":
      return order.result === null ? (
        <Message text={copy.site.loading} />
      ) : (
        <Result id={id} token={token} config={config} result={order.result} feedbackSent={order.feedback_sent} onDeleted={() => void refresh()} />
      )
    case "failed":
      return <Failed order={order} />
    case "paused":
      return <Message text={t.paused} />
    case "expired":
      return <Message text={t.expired} action />
    case "abandoned":
      return <Message text={t.abandoned} action />
    case "deleted":
      return <Message text={t.deleted} />
    default:
      // A status newer than this build: log it and show a neutral line instead of a blank page.
      console.error("unknown order status", { status: String(order.status) })
      return <Message text={copy.site.loading} />
  }
}

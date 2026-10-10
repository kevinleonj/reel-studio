import { Check, LoaderCircle } from "lucide-react"

import { buttonVariants } from "@/components/ui/button"
import { copy, format, pluralize } from "@/lib/copy"
import { toMinutes } from "@/lib/format"
import type { FailureCode, OrderView, StageKey } from "@/lib/types"

// Every order status except `paid` and `done` (docs/UX.md §2 order page table).
const t = copy.order

type Retry = "startAgain" | "fewerClips" | null
// Retry offered per failure (docs/EDITOR.md §10).
const RETRY: Record<FailureCode, Retry> = {
  no_usable_input: "startAgain",
  model_refusal: null,
  cost_cap: "fewerClips",
  output_too_long: "startAgain",
  provider_unavailable: "startAgain",
  render_error: "startAgain",
  job_killed: "startAgain",
}

export function Message({ text, action }: { text: string; action?: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">{text}</h1>
      {action && (
        <a href="/new" className={buttonVariants({ size: "lg" })}>
          {t.startAgain}
        </a>
      )}
    </div>
  )
}

function ClosePage({ emailHint }: { emailHint: string | null }) {
  return <p className="text-muted-foreground">{emailHint ? format(t.closePage, { email: emailHint }) : t.closePageNoEmail}</p>
}

export function Queued({ order }: { order: OrderView }) {
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-2xl font-semibold tracking-tight">{t.queued.waiting}</h1>
      {order.queue_position !== null && order.queue_position > 0 && (
        <p>{pluralize(t.queued.aheadOne, t.queued.aheadOther, order.queue_position)}</p>
      )}
      <ClosePage emailHint={order.email_hint} />
    </div>
  )
}

function visibleStages(order: OrderView): StageKey[] {
  const current = order.stage?.name
  const happened = (key: StageKey) => order.stages_done.includes(key) || current === key
  const stages: StageKey[] = ["reading"]
  if (order.settings.keep_voice) stages.push("listening")
  stages.push("planning", "rendering", "checking")
  if (happened("revising")) stages.push("revising")
  stages.push("saving")
  return stages
}

export function Running({ order }: { order: OrderView }) {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">{t.stagesLabel}</h1>
      <ol className="flex flex-col gap-2" aria-label={t.stagesLabel}>
        {visibleStages(order).map((key) => {
          const done = order.stages_done.includes(key)
          const current = order.stage?.name === key
          return (
            <li
              key={key}
              aria-current={current ? "step" : undefined}
              className={`flex min-h-target items-center gap-3 ${done || current ? "" : "text-muted-foreground"}`}
            >
              {done && <Check aria-hidden="true" className="size-5 text-success" />}
              {current && <LoaderCircle aria-hidden="true" className="size-5 animate-spin text-primary" />}
              {!done && !current && <span aria-hidden="true" className="size-5" />}
              <span className={current ? "font-medium" : ""}>{t.stages[key]}</span>
              {current && order.stage !== null && (
                <span className="text-sm text-muted-foreground">{format(t.elapsed, { minutes: toMinutes(order.stage.elapsed_s) })}</span>
              )}
            </li>
          )
        })}
      </ol>
      <ClosePage emailHint={order.email_hint} />
    </div>
  )
}

export function Failed({ order }: { order: OrderView }) {
  // An unknown code (a newer editor than this page) falls back to the generic cutting failure.
  const raw = order.error?.code
  const code: FailureCode = raw !== undefined && Object.hasOwn(RETRY, raw) ? raw : "render_error"
  const message = t.failed.messages[code]
  const retry = RETRY[code]
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">{message}</h1>
      {!message.includes(t.failed.notified) && <p>{t.failed.notified}</p>}
      {retry !== null && (
        <a href="/new" className={buttonVariants({ size: "lg" })}>
          {t.failed[retry]}
        </a>
      )}
    </div>
  )
}

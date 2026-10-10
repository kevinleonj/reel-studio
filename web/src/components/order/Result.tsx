import { useEffect, useRef, useState } from "react"
import { Check, Copy, Download } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { track } from "@/lib/analytics"
import { api } from "@/lib/api"
import { copy, format } from "@/lib/copy"
import { formatClock } from "@/lib/format"
import type { AppConfig, OrderResult, ReelVersion } from "@/lib/types"

// The `done` state (docs/UX.md §2 "Result"), sections 1–10 in order.
const t = copy.result
const VERSION_ORDER: ReelVersion["kind"][] = ["text", "clean"]

function Heading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xl font-semibold">{children}</h2>
}

function Players({ versions }: { versions: ReelVersion[] }) {
  const sorted = [...versions].sort((a, b) => VERSION_ORDER.indexOf(a.kind) - VERSION_ORDER.indexOf(b.kind))
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {sorted.map((version) => {
        const label = version.kind === "text" ? t.withText : t.clean
        return (
          <figure key={version.kind} className="flex flex-col gap-2" data-testid={`player-${version.kind}`}>
            <figcaption className="font-medium">{label}</figcaption>
            <video src={version.play_url} controls playsInline preload="metadata" aria-label={label} className="aspect-9/16 w-full rounded-lg bg-muted" />
            <a
              href={version.download_url}
              download
              className="inline-flex min-h-target items-center justify-center gap-2 rounded-lg border border-input px-4 font-medium hover:bg-muted"
              aria-label={format(t.downloadVersion, { version: label })}
              onClick={() => track("reel_download", { version: version.kind })}
            >
              <Download aria-hidden="true" className="size-4" />
              {t.download}
            </a>
          </figure>
        )
      })}
    </div>
  )
}

/**
 * navigator.clipboard exists only in a secure context; on the laptop tier a phone opens
 * http://<laptop-ip>:8080, so fall back to selecting a hidden textarea and execCommand("copy").
 */
async function writeClipboard(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard !== undefined) {
    await navigator.clipboard.writeText(text)
    return true
  }
  const before = document.activeElement
  const area = document.createElement("textarea")
  area.value = text
  area.setAttribute("readonly", "")
  area.className = "sr-only"
  document.body.append(area)
  area.select()
  area.setSelectionRange(0, text.length) // iOS Safari ignores select() alone
  const ok = document.execCommand("copy")
  area.remove()
  if (before instanceof HTMLElement) before.focus() // keep keyboard focus on the Copy button
  return ok
}

function Caption({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle")
  const copied = state === "copied"
  const copyCaption = async () => {
    try {
      setState((await writeClipboard(text)) ? "copied" : "failed")
    } catch (error) {
      console.error("clipboard write failed", { error: String(error) })
      setState("failed")
    }
  }
  return (
    <section className="flex flex-col gap-2">
      <Heading>{t.caption}</Heading>
      <p className="whitespace-pre-wrap rounded-lg bg-muted p-3" data-testid="caption">
        {text}
      </p>
      <Button variant="outline" onClick={() => void copyCaption()}>
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        {copied ? t.copied : t.copy}
      </Button>
      {state === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          {t.copyFailed}
        </p>
      )}
    </section>
  )
}

function Feedback({ id, token, max, commentMax, alreadySent }: { id: string; token: string; max: number; commentMax: number; alreadySent: boolean }) {
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState("")
  const [sent, setSent] = useState(alreadySent)
  const [failed, setFailed] = useState(false)
  if (sent) return <p>{t.sent}</p>
  const send = async () => {
    try {
      await api.feedback(id, token, rating, comment)
      track("feedback_sent", { rating })
      setSent(true)
    } catch (error) {
      console.error("feedback failed", { error: String(error) })
      setFailed(true)
    }
  }
  return (
    <section className="flex flex-col gap-3">
      <Heading>{t.feedback}</Heading>
      <div className="flex gap-2" role="group" aria-label={t.feedback}>
        {Array.from({ length: max }, (_, i) => i + 1).map((value) => (
          <Button
            key={value}
            variant={value === rating ? "default" : "outline"}
            aria-pressed={value === rating}
            aria-label={format(t.ratingLabel, { rating: value, max })}
            className="size-target"
            onClick={() => setRating(value)}
          >
            {value}
          </Button>
        ))}
      </div>
      <Label htmlFor="comment">
        {t.comment}
        <span className="ml-2 font-normal text-muted-foreground">{t.commentOptional}</span>
      </Label>
      <Textarea id="comment" value={comment} maxLength={commentMax} onChange={(e) => setComment(e.target.value)} />
      {failed && <p role="alert" className="text-destructive">{copy.form.errors.network}</p>}
      <Button disabled={rating === 0} onClick={() => void send()}>
        {t.send}
      </Button>
    </section>
  )
}

function DeleteFiles({ id, token, onDeleted }: { id: string; token: string; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [failed, setFailed] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)
  const keepButton = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef(false)
  useEffect(() => {
    // Keep keyboard and screen-reader focus on the control that replaced the one just pressed;
    // an irreversible step starts on the safe choice (WAI-ARIA APG, alert dialog).
    if (confirming) keepButton.current?.focus()
    else if (returnFocus.current) opener.current?.focus()
  }, [confirming])
  const remove = async () => {
    try {
      await api.deleteFiles(id, token)
      onDeleted()
    } catch (error) {
      console.error("delete failed", { error: String(error) })
      setFailed(true)
    }
  }
  if (!confirming) {
    return (
      <Button ref={opener} variant="outline" onClick={() => setConfirming(true)}>
        {t.deleteNow}
      </Button>
    )
  }
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-destructive p-4" role="group" aria-labelledby="delete-confirm">
      <p id="delete-confirm" className="font-medium">
        {t.deleteConfirm}
      </p>
      {failed && <p role="alert" className="text-destructive">{copy.form.errors.network}</p>}
      <div className="flex gap-2">
        <Button variant="destructive" onClick={() => void remove()}>
          {t.delete}
        </Button>
        <Button
          ref={keepButton}
          variant="outline"
          onClick={() => {
            returnFocus.current = true
            setConfirming(false)
          }}
        >
          {t.keep}
        </Button>
      </div>
    </div>
  )
}

interface ResultProps {
  id: string
  token: string
  config: AppConfig
  result: OrderResult
  feedbackSent: boolean
  onDeleted: () => void
}

export function Result({ id, token, config, result, feedbackSent, onDeleted }: ResultProps) {
  return (
    <div className="flex flex-col gap-8">
      <h1 className="text-3xl font-semibold tracking-tight">{t.heading}</h1>
      <Players versions={result.versions} />
      <Caption text={result.caption} />
      <section className="flex flex-col gap-2">
        <Heading>{t.textLines}</Heading>
        <ul className="flex flex-col gap-1">
          {result.text_lines.map((line) => (
            <li key={`${line.at_s}-${line.text}`}>{format(t.textLine, { time: formatClock(line.at_s), text: line.text })}</li>
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-1">
        <Heading>{t.music}</Heading>
        <p>{format(t.musicLine, { mood: result.music.mood, tempo: result.music.tempo })}</p>
        <p className="text-muted-foreground">{t.musicHint}</p>
      </section>
      {result.left_out.length > 0 && (
        <section className="flex flex-col gap-2">
          <Heading>{t.leftOut}</Heading>
          <ul className="list-disc pl-6">
            {result.left_out.map((item) => (
              <li key={item.file}>{format(t.leftOutLine, { file: item.file, reason: item.reason })}</li>
            ))}
          </ul>
        </section>
      )}
      {result.wishes.length > 0 && (
        <section className="flex flex-col gap-2">
          <Heading>{t.wishes}</Heading>
          <ul className="list-disc pl-6">
            {result.wishes.map((wish) => (
              <li key={wish.wish}>
                {format(t.wishLine, { wish: wish.wish, state: wish.applied ? t.applied : t.notApplied, reason: wish.reason })}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="flex flex-col gap-2">
        <Heading>{t.check}</Heading>
        <ul className="list-disc pl-6">
          {result.doubts.map((doubt) => (
            <li key={doubt}>{doubt}</li>
          ))}
        </ul>
        <p className="font-medium">{t.aiLine}</p>
      </section>
      <Feedback id={id} token={token} max={config.feedback.rating_max} commentMax={config.feedback.comment_max_chars} alreadySent={feedbackSent} />
      <DeleteFiles id={id} token={token} onDeleted={onDeleted} />
      <p className="text-sm text-muted-foreground">{t.retention}</p>
    </div>
  )
}

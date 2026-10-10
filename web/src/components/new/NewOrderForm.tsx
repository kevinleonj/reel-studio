import { useEffect, useState } from "react"

import { ErrorBoundary } from "@/components/ErrorBoundary"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { track } from "@/lib/analytics"
import { ApiError, api } from "@/lib/api"
import { loadConfig } from "@/lib/config"
import { copy } from "@/lib/copy"
import type { AppConfig, OrderSettings } from "@/lib/types"
import { Chips, LanguagePicker, LengthPicker, NoteField, StyleCards, VoiceToggle } from "./fields"

const t = copy.form
type ErrorKey = keyof typeof t.errors

function errorKey(error: unknown): ErrorKey {
  if (error instanceof ApiError && error.code !== null && error.code in t.errors) return error.code as ErrorKey
  return "network"
}

/** Text language from the browser: es* -> Spanish, else English (docs/UX.md §1). */
function browserLanguage(available: string[]): string {
  const wanted = navigator.language.toLowerCase().startsWith("es") ? "es" : "en"
  return available.includes(wanted) ? wanted : available[0]
}

/**
 * Stripe's Cancel returns to /new?cancel=<order_id>&t=<token>: release the place, refill the form.
 * The refill is optional: if it fails, the empty form stays usable and the link is kept for a reload.
 */
async function takeCancelled(): Promise<OrderSettings | null> {
  const url = new URL(window.location.href)
  const id = url.searchParams.get("cancel")
  const token = url.searchParams.get("t")
  if (id === null || token === null) return null
  try {
    const { settings } = await api.cancel(id, token)
    url.search = ""
    window.history.replaceState(null, "", url.toString())
    return settings
  } catch (error) {
    console.error("could not release the cancelled checkout; showing an empty form", { error: String(error) })
    return null
  }
}

export function NewOrderForm() {
  return (
    <ErrorBoundary>
      <NewOrderFormInner />
    </ErrorBoundary>
  )
}

function NewOrderFormInner() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [style, setStyle] = useState("")
  const [length, setLength] = useState(0)
  const [textLang, setTextLang] = useState("")
  const [keepVoice, setKeepVoice] = useState(false)
  const [voiceTouched, setVoiceTouched] = useState(false)
  const [chips, setChips] = useState<string[]>([])
  const [note, setNote] = useState("")
  const [code, setCode] = useState("")
  const [email, setEmail] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ErrorKey | null>(null)

  useEffect(() => {
    const load = async () => {
      const loaded = await loadConfig()
      setConfig(loaded)
      setLength(loaded.default_length_s)
      setTextLang(browserLanguage(loaded.text_languages))
      const refill = await takeCancelled()
      if (refill !== null) {
        setStyle(refill.style)
        setLength(refill.length_s)
        setTextLang(refill.text_lang)
        setKeepVoice(refill.keep_voice)
        setVoiceTouched(true)
        setChips(refill.chips)
        setNote(refill.note)
      }
    }
    load().catch((err: unknown) => {
      console.error("could not load the form", { error: String(err) })
      setLoadError(true)
    })
  }, [])

  useEffect(() => {
    // Back from Stripe restores this page from the back-forward cache with "Opening checkout…".
    const onShow = (event: PageTransitionEvent) => {
      if (event.persisted) setSubmitting(false)
    }
    window.addEventListener("pageshow", onShow)
    return () => window.removeEventListener("pageshow", onShow)
  }, [])

  if (loadError) return <p role="alert">{t.errors.network}</p>
  if (config === null) return <p className="text-muted-foreground">{copy.site.loading}</p>

  const needsCode = config.payments !== "off"
  const ready = style !== "" && (!needsCode || code.trim() !== "") && !submitting

  const chooseStyle = (key: string) => {
    setStyle(key)
    // The voice toggle follows the style until the user touches it (docs/UX.md §6 item 4).
    if (!voiceTouched) setKeepVoice(config.styles.find((s) => s.key === key)?.voice_default ?? false)
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!ready) return
    setSubmitting(true)
    setError(null)
    const settings: OrderSettings = {
      style,
      length_s: length,
      text_lang: textLang,
      keep_voice: config.voice_available && keepVoice,
      chips,
      note,
    }
    track("generate_lead", { style, length })
    try {
      const response = await api.checkout(settings, code.trim(), email.trim())
      const target = response.checkout_url ?? response.order_url
      if (target === undefined) throw new Error("checkout answered without a link")
      if (response.checkout_url !== undefined && config.price !== null) {
        track("begin_checkout", { value: config.price.value, currency: config.price.currency })
      }
      window.location.assign(target)
    } catch (err) {
      console.error("checkout failed", { error: String(err) })
      setError(errorKey(err))
      setSubmitting(false)
    }
  }

  const errorLine = error !== null && (
    <p id="form-error" role="alert" className="text-sm font-medium text-destructive">
      {t.errors[error]}
    </p>
  )

  return (
    <form onSubmit={submit} className="flex flex-col gap-8" noValidate>
      <h1 className="text-3xl font-semibold tracking-tight">{t.heading}</h1>
      <StyleCards config={config} value={style} onChange={chooseStyle} />
      <LengthPicker config={config} value={length} onChange={setLength} />
      <LanguagePicker config={config} value={textLang} onChange={setTextLang} />
      <VoiceToggle
        available={config.voice_available}
        checked={keepVoice}
        onChange={(on) => {
          setVoiceTouched(true)
          setKeepVoice(on)
        }}
      />
      <Chips config={config} value={chips} onChange={setChips} />
      <NoteField max={config.note_max_chars} value={note} onChange={setNote} />
      {needsCode ? (
        <section className="flex flex-col gap-2">
          <Label htmlFor="code" className="text-lg font-semibold">
            {t.code.label}
            <span className="ml-2 text-sm font-normal text-muted-foreground">{t.code.required}</span>
          </Label>
          <Input
            id="code"
            value={code}
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={error !== null && error !== "network"}
            aria-describedby={error !== null ? "form-error" : undefined}
            onChange={(e) => setCode(e.target.value)}
          />
          {errorLine}
        </section>
      ) : (
        <section className="flex flex-col gap-2">
          <Label htmlFor="email" className="text-lg font-semibold">
            {t.email.label}
          </Label>
          <Input
            id="email"
            type="email"
            value={email}
            autoComplete="email"
            aria-describedby="email-help"
            onChange={(e) => setEmail(e.target.value)}
          />
          <p id="email-help" className="text-sm text-muted-foreground">
            {t.email.help}
          </p>
          {errorLine}
        </section>
      )}
      <Button type="submit" size="lg" disabled={!ready}>
        {submitting ? t.opening : t.continue}
      </Button>
    </form>
  )
}

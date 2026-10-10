import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { track } from "@/lib/analytics"
import { ApiError, api } from "@/lib/api"
import { copy, format } from "@/lib/copy"
import { formatGb, formatSize, toMb, toPercent } from "@/lib/format"
import type { AppConfig, UploadError } from "@/lib/types"
import { UploadFailed, checkSettings, createPool, uploadFile, type UploadSettings } from "@/lib/upload"

// The `paid` state: choose files, upload them resumably, then Start (docs/UX.md §2).
const t = copy.order.upload
type RowState = "waiting" | "uploading" | "done" | "failed"
interface Row {
  key: string
  name: string
  size: number
  sent: number
  state: RowState
  file?: File
  url?: string
}

let nextKey = 0
const newKey = () => `row-${(nextKey += 1)}`

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code !== null && error.code in t.errors) {
    return format(t.errors[error.code as UploadError], { name: error.file ?? "" })
  }
  return t.errors.network
}

function settingsFrom(config: AppConfig): UploadSettings {
  const settings = {
    chunkBytes: config.upload.chunk_bytes,
    maxTries: config.upload.chunk_retries,
    backoffMs: config.upload.backoff_ms,
    timeoutMs: config.timeouts.chunk_ms,
  }
  checkSettings(settings) // a bad server config is a bug: the island's error boundary shows it
  return settings
}

interface Props {
  id: string
  token: string
  config: AppConfig
  /** Start succeeded; the parent keeps polling until the status moves on. */
  onStarted: () => void
}

export function UploadPanel({ id, token, config, onStarted }: Props) {
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const reported = useRef(false)
  const [settings] = useState(() => settingsFrom(config))
  // One queue for the whole page: every batch and every Retry share the same two slots.
  const [pool] = useState(() => createPool(config.upload.parallel_files))

  const patch = (key: string, change: Partial<Row>) =>
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)))

  useEffect(() => {
    // After a reload, finished files are listed again; unfinished ones must be chosen again.
    // Merge by name: files chosen before the listing arrives must not disappear.
    api
      .listFiles(id, token)
      .then(({ files }) =>
        setRows((current) => {
          const known = new Set(current.map((row) => row.name))
          const listed = files
            .filter((f) => !known.has(f.name))
            .map((f) => ({ key: newKey(), name: f.name, size: f.size, sent: f.size, state: "done" as const }))
          return [...listed, ...current]
        })
      )
      .catch((err: unknown) => {
        console.error("could not list finished files", { error: String(err) })
        setError(t.errors.network)
      })
  }, [id, token])

  useEffect(() => {
    // upload_complete once, when every file chosen on this page has finished.
    const uploadedHere = rows.filter((row) => row.file !== undefined)
    if (reported.current || uploadedHere.length === 0 || rows.some((row) => row.state !== "done")) return
    reported.current = true
    const total = rows.reduce((sum, row) => sum + row.size, 0)
    track("upload_complete", { file_count: rows.length, total_mb: toMb(total) })
  }, [rows])

  const send = (row: Row, resume = false) =>
    pool(async () => {
      if (row.file === undefined || row.url === undefined) return
      patch(row.key, { state: "uploading" })
      try {
        await uploadFile(row.url, row.file, settings, (sent) => patch(row.key, { sent }), resume)
        patch(row.key, { state: "done", sent: row.size })
      } catch (err) {
        if (!(err instanceof UploadFailed)) throw err
        console.error("upload failed", { file: row.name, error: String(err) })
        patch(row.key, { state: "failed" })
      }
    })

  const retry = (row: Row) => {
    patch(row.key, { state: "waiting" })
    void send(row, true)
  }

  const choose = async (list: FileList | null) => {
    const files = Array.from(list ?? [])
    if (input.current !== null) input.current.value = ""
    if (files.length === 0) return
    const empty = files.find((f) => f.size === 0)
    if (empty !== undefined) {
      // Phones can hand over 0-byte placeholders; uploading one would only fail later.
      setError(format(t.errors.empty, { name: empty.name }))
      return
    }
    setError(null)
    try {
      const { targets } = await api.createUploads(
        id,
        token,
        files.map((f) => ({ name: f.name, size: f.size, type: f.type }))
      )
      const added: Row[] = files.map((file, index) => ({
        key: newKey(),
        name: file.name,
        size: file.size,
        sent: 0,
        state: "waiting",
        file,
        url: targets[index]?.upload_url,
      }))
      reported.current = false
      setRows((current) => [...current, ...added])
      await Promise.all(added.map((row) => send(row)))
    } catch (err) {
      console.error("could not create upload sessions", { error: String(err) })
      setError(errorMessage(err))
    }
  }

  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      await api.start(id, token)
      onStarted()
    } catch (err) {
      console.error("start failed", { error: String(err) })
      setError(errorMessage(err))
      setStarting(false)
    }
  }

  const used = rows.reduce((sum, row) => sum + row.size, 0)
  const busy = rows.some((row) => row.state === "uploading" || row.state === "waiting" || row.state === "failed")
  const canStart = rows.some((row) => row.state === "done") && !busy && !starting
  const limits = config.limits

  return (
    <section className="flex flex-col gap-4" aria-labelledby="upload-heading">
      <h1 id="upload-heading" className="text-3xl font-semibold tracking-tight">
        {t.heading}
      </h1>
      <p className="text-muted-foreground">
        {format(t.limits, {
          maxFiles: limits.max_files,
          maxSize: formatGb(limits.max_total_bytes),
          maxMinutes: limits.max_file_minutes,
        })}
      </p>
      {error !== null && (
        <p role="alert" className="font-medium text-destructive">
          {error}
        </p>
      )}
      <input
        ref={input}
        id="files"
        type="file"
        multiple
        accept="video/*,image/*"
        className="sr-only"
        tabIndex={-1}
        aria-label={t.choose}
        onChange={(e) => void choose(e.target.files)}
      />
      <Button variant={rows.length ? "outline" : "default"} size="lg" onClick={() => input.current?.click()}>
        {rows.length ? t.addMore : t.choose}
      </Button>
      {rows.length > 0 && (
        <ul className="flex flex-col gap-3">
          {rows.map((row) => (
            <li key={row.key} className="flex flex-col gap-2 rounded-lg border p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate font-medium">{row.name}</span>
                <span className="shrink-0 text-sm text-muted-foreground">{formatSize(row.size)}</span>
              </div>
              <Progress value={toPercent(row.sent, row.size)} aria-label={format(t.progressLabel, { name: row.name })} />
              <div className="flex min-h-target items-center justify-between text-sm">
                <span className={row.state === "failed" ? "text-destructive" : "text-muted-foreground"}>
                  {format(t.state[row.state], { percent: toPercent(row.sent, row.size) })}
                </span>
                {row.state === "failed" && (
                  <Button variant="outline" onClick={() => retry(row)}>
                    {t.retry}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="text-sm text-muted-foreground">
        {format(t.total, {
          used: formatGb(used),
          max: formatGb(limits.max_total_bytes),
          count: rows.length,
          maxFiles: limits.max_files,
        })}
      </p>
      {busy && <p className="text-sm font-medium sm:hidden">{t.keepOpen}</p>}
      <Button size="lg" disabled={!canStart} onClick={() => void start()}>
        {t.start}
      </Button>
    </section>
  )
}

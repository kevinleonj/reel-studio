// Resumable chunked upload (docs/UX.md §2 "Upload behaviour", D54, FACTS F307). Same protocol for
// Cloud Storage resumable sessions and the laptop's /api/local-upload: each chunk is a PUT with
// `Content-Range: bytes <first>-<last>/<total>`; 308 = keep going (its `Range` says what the
// session persisted, which may be less than was sent), 200/201 = finished. After a failed chunk,
// an empty PUT with `bytes */<total>` asks the session how much it already has.
// No React here, so the logic stays testable on its own.

const HTTP_OK = 200
const HTTP_CREATED = 201
const HTTP_RESUME_INCOMPLETE = 308
const RANGE_END = /bytes=\d+-(\d+)/
/** Cloud Storage: every chunk except the last must be a multiple of 256 KiB (F307). */
export const CHUNK_MULTIPLE = 262_144 // 256 KiB

export interface UploadSettings {
  chunkBytes: number
  maxTries: number
  backoffMs: number
  /** Per request; a stalled PUT counts as a failed try. */
  timeoutMs: number
}

export class UploadFailed extends Error {}

type Probe = { done: true } | { done: false; offset: number }

export function checkSettings(settings: UploadSettings): void {
  if (settings.chunkBytes <= 0 || settings.chunkBytes % CHUNK_MULTIPLE !== 0) {
    throw new Error(`upload.chunk_bytes must be a positive multiple of ${CHUNK_MULTIPLE}, got ${settings.chunkBytes}`)
  }
}

function readProbe(response: Response): Probe {
  if (response.status === HTTP_OK || response.status === HTTP_CREATED) return { done: true }
  if (response.status !== HTTP_RESUME_INCOMPLETE) throw new UploadFailed(`HTTP ${response.status}`)
  const match = RANGE_END.exec(response.headers.get("Range") ?? "")
  return { done: false, offset: match ? Number(match[1]) + 1 : 0 }
}

async function askOffset(url: string, total: number, settings: UploadSettings): Promise<Probe> {
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Range": `bytes */${total}` },
    signal: AbortSignal.timeout(settings.timeoutMs),
  })
  return readProbe(response)
}

async function sendChunk(url: string, file: Blob, offset: number, settings: UploadSettings): Promise<Probe> {
  const end = Math.min(offset + settings.chunkBytes, file.size)
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Range": `bytes ${offset}-${end - 1}/${file.size}` },
    body: file.slice(offset, end),
    signal: AbortSignal.timeout(settings.timeoutMs),
  })
  return readProbe(response)
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Uploads one file; calls onProgress(bytesConfirmed). Throws UploadFailed after maxTries failures
 * in a row. `resume` (a Retry on the same session) first asks the session for its offset.
 */
export async function uploadFile(
  url: string,
  file: Blob,
  settings: UploadSettings,
  onProgress: (bytes: number) => void,
  resume = false
): Promise<void> {
  // Finalising an empty object is UNCONFIRMED for Cloud Storage (F307); the panel refuses empty
  // files before they get here, so this only guards against a caller that forgets.
  if (file.size === 0) throw new UploadFailed("empty file")
  let offset = 0
  let failures = 0
  // Highest offset the session has confirmed. Progress seen in a status query resets the
  // failure streak: on a slow link a chunk can time out after its bytes were kept.
  let confirmed = 0
  if (resume) {
    const probe = await askOffset(url, file.size, settings).catch((error: unknown) => {
      throw new UploadFailed(String(error))
    })
    if (probe.done) return onProgress(file.size)
    offset = probe.offset
    confirmed = offset
  }
  while (offset < file.size) {
    try {
      const probe = await sendChunk(url, file, offset, settings)
      if (probe.done) break
      // A 308 that persisted nothing new would loop forever without spending a try.
      if (probe.offset <= offset) throw new UploadFailed(`no progress at offset ${offset}`)
      offset = probe.offset
      confirmed = Math.max(confirmed, offset)
      failures = 0
      onProgress(offset)
    } catch (error) {
      failures += 1
      console.warn("upload chunk failed", { offset, failures, error: String(error) })
      if (failures >= settings.maxTries) throw new UploadFailed(String(error))
      await sleep(settings.backoffMs * 2 ** (failures - 1))
      try {
        const probe = await askOffset(url, file.size, settings)
        if (probe.done) break
        offset = probe.offset
        if (offset > confirmed) {
          // The session kept bytes despite the error: that is progress, not a failed try.
          confirmed = offset
          failures = 0
          onProgress(offset)
        }
      } catch (probeError) {
        // Resending from the old offset is safe: the session ignores bytes it already has (F307).
        console.warn("offset query failed", { offset, error: String(probeError) })
      }
    }
  }
  onProgress(file.size)
}

/**
 * A queue with at most `limit` uploads in flight across every batch and every Retry on the
 * page (two files at a time, docs/UX.md §2).
 */
export function createPool(limit: number) {
  const slots = Math.max(1, limit)
  const waiting: (() => void)[] = []
  let running = 0
  const next = () => {
    if (running >= slots) return
    const start = waiting.shift()
    if (start !== undefined) start()
  }
  return function run(task: () => Promise<void>): Promise<void> {
    return new Promise((resolve, reject) => {
      waiting.push(() => {
        running += 1
        Promise.resolve()
          .then(task) // a task that throws synchronously still frees its slot
          .then(resolve, reject)
          .finally(() => {
            running -= 1
            next()
          })
      })
      next()
    })
  }
}

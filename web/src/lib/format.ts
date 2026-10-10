// Display formats. Sizes are decimal (4 GB = 4,000,000,000 bytes, as in config/limits.toml).
const BYTES_PER_GB = 1_000_000_000
const BYTES_PER_MB = 1_000_000
const SECONDS_PER_MINUTE = 60
const PERCENT = 100

const gb = new Intl.NumberFormat("en", { style: "unit", unit: "gigabyte", maximumFractionDigits: 1 })

export function formatGb(bytes: number): string {
  return gb.format(bytes / BYTES_PER_GB)
}

const mb = new Intl.NumberFormat("en", { style: "unit", unit: "megabyte", maximumFractionDigits: 0 })

/** File sizes: MB below 1 GB, GB above. */
export function formatSize(bytes: number): string {
  return bytes >= BYTES_PER_GB ? formatGb(bytes) : mb.format(bytes / BYTES_PER_MB)
}

export function toMb(bytes: number): number {
  return Math.round(bytes / BYTES_PER_MB)
}

export function toMinutes(seconds: number): number {
  return Math.floor(seconds / SECONDS_PER_MINUTE)
}

export function toPercent(done: number, total: number): number {
  return total > 0 ? Math.floor((done / total) * PERCENT) : 0
}

const clock = new Intl.NumberFormat("en", { minimumIntegerDigits: 2 })

/** 75.4 -> "1:15" */
export function formatClock(seconds: number): string {
  const whole = Math.floor(seconds)
  return `${Math.floor(whole / SECONDS_PER_MINUTE)}:${clock.format(whole % SECONDS_PER_MINUTE)}`
}

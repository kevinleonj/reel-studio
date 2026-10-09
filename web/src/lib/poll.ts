import { useEffect, useRef } from "react"

const MS_PER_SECOND = 1000

// Polls every `seconds` while the tab is visible, and at once when it becomes visible again
// (D16: phones pause background tabs).
export function usePolling(callback: () => void, seconds: number, active: boolean): void {
  const saved = useRef(callback)
  useEffect(() => {
    saved.current = callback
  }, [callback])

  useEffect(() => {
    if (!active) return
    const tick = () => {
      if (document.visibilityState === "visible") saved.current()
    }
    const timer = window.setInterval(tick, seconds * MS_PER_SECOND)
    document.addEventListener("visibilitychange", tick)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener("visibilitychange", tick)
    }
  }, [seconds, active])
}

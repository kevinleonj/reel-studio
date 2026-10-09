import { Component, type ReactNode } from "react"

import { copy } from "@/lib/copy"

// Keeps a render error from leaving an empty page: the island shows one line and logs the cause.
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error("island crashed", { error: String(error) })
  }

  render() {
    if (this.state.failed) return <p role="alert">{copy.site.broken}</p>
    return this.props.children
  }
}

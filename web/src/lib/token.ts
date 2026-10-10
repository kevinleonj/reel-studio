// The order token lives after `#` (D18) so it never reaches a server log. Stripe's success
// redirect brings it as `?t=`; it moves behind `#` at once (docs/ARCHITECTURE.md §7).
const PARAM = "t"

export function takeToken(): string | null {
  const url = new URL(window.location.href)
  const fromQuery = url.searchParams.get(PARAM)
  if (fromQuery !== null) {
    url.searchParams.delete(PARAM)
    url.hash = new URLSearchParams({ [PARAM]: fromQuery }).toString()
    window.history.replaceState(null, "", url.toString())
    return fromQuery
  }
  return new URLSearchParams(url.hash.slice(1)).get(PARAM)
}

/** `/o/<id>` -> `<id>`; the static shell serves every id. */
export function orderIdFromPath(): string | null {
  const parts = window.location.pathname.split("/").filter(Boolean)
  if (parts.length !== 2 || parts[0] !== "o") return null
  try {
    return decodeURIComponent(parts[1])
  } catch (error) {
    console.warn("order id in the path is not valid percent-encoding", { error: String(error) })
    return null
  }
}

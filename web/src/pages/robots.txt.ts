import type { APIRoute } from "astro"

// robots.txt allows everything and names the sitemap (docs/UX.md §2). /new and /o/* are not
// listed: a blocked page never shows its noindex (F69).
export const GET: APIRoute = ({ site }) => {
  if (site === undefined) throw new Error("site is not set in astro.config.mjs (SITE_URL)")
  const sitemap = new URL("sitemap-index.xml", site)
  return new Response(`User-agent: *\nAllow: /\n\nSitemap: ${sitemap.href}\n`)
}

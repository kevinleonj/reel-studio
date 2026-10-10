// @ts-check
import { fileURLToPath } from "node:url"

import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "astro/config"
import { loadEnv } from "vite"

// .env files are not loaded inside the Astro config; loadEnv is the documented way
// (docs.astro.build/en/guides/environment-variables). The repository's .env lives one level up.
const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url))
const { SITE_URL } = loadEnv(process.env.NODE_ENV ?? "", REPO_ROOT, "SITE_")
if (!SITE_URL) {
  throw new Error("SITE_URL is not set: add it to .env or the environment (canonical links, sitemap, robots.txt).")
}

// Only the two public pages are listed; /new and /o/* are noindex shells (docs/UX.md §2).
const INDEXED_PATHS = new Set(["/", "/privacy/"])

export default defineConfig({
  site: SITE_URL,
  output: "static",
  vite: {
    plugins: [tailwindcss()],
  },
  integrations: [
    react(),
    sitemap({ filter: (page) => INDEXED_PATHS.has(new URL(page).pathname) }),
  ],
})

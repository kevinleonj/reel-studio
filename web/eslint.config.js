import js from "@eslint/js"
import globals from "globals"
import react from "eslint-plugin-react"
import reactHooks from "eslint-plugin-react-hooks"
import tseslint from "typescript-eslint"
import { defineConfig, globalIgnores } from "eslint/config"

// Literal rules (D76, STEP-06 task 3). Values live in /api/config, text in src/copy/en.json,
// colours and sizes in src/styles/tokens.css. tests/eslint-policy.test.mjs keeps these at "error".
const URL_LITERALS = [
  { selector: "Literal[value=/^https?:\\/\\//i]", message: "URLs come from /api/config, not web code." },
  { selector: "TemplateElement[value.raw=/https?:\\/\\//i]", message: "URLs come from /api/config, not web code." },
]
const OTHER_LITERALS = [
  {
    selector: "Literal[value=/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/]",
    message: "Colours live in src/styles/tokens.css.",
  },
  {
    // jsx-no-literals ignores props (className must stay legal); visible-text props are caught here.
    selector: "JSXAttribute[name.name=/^(aria-label|placeholder|alt|title|label)$/] > Literal",
    message: "Visible text comes from src/copy/en.json.",
  },
]

export default defineConfig([
  globalIgnores(["dist", ".astro", "node_modules", "test-results", "playwright-report"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { react },
    settings: { react: { version: "detect" } },
    rules: {
      "no-magic-numbers": ["error", { ignore: [-1, 0, 1, 2], ignoreArrayIndexes: true }],
      "react/jsx-no-literals": ["error", { noStrings: true, ignoreProps: true }],
      "no-restricted-syntax": ["error", ...URL_LITERALS, ...OTHER_LITERALS],
    },
  },
])

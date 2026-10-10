// Policy test (STEP-06, D76): the literal rules must stay errors for TypeScript/React files.
// Runs `eslint --print-config` on one real .tsx file and reads the resolved severities.
import { execFileSync } from "node:child_process"
import { test } from "node:test"
import assert from "node:assert/strict"

const SAMPLE = "src/components/ui/button.tsx"
const REQUIRED = ["no-magic-numbers", "react/jsx-no-literals", "no-restricted-syntax"]
const ERROR = 2

function resolvedRules() {
  const out = execFileSync("npx", ["eslint", "--print-config", SAMPLE], { encoding: "utf8" })
  return JSON.parse(out).rules ?? {}
}

test("literal rules are errors on .tsx files", () => {
  const rules = resolvedRules()
  for (const name of REQUIRED) {
    const entry = rules[name]
    const severity = Array.isArray(entry) ? entry[0] : entry
    assert.ok(severity === ERROR || severity === "error", `${name} must be "error", got ${JSON.stringify(entry)}`)
  }
})

test("no-restricted-syntax still bans URL strings, hex colours and literal text props", () => {
  const selectors = (resolvedRules()["no-restricted-syntax"] ?? []).slice(1).map((option) => option.selector ?? option)
  const joined = selectors.join("\n")
  for (const needle of ["https?", "0-9a-fA-F", "aria-label"]) {
    assert.ok(joined.includes(needle), `no-restricted-syntax lost its selector containing ${needle}`)
  }
})

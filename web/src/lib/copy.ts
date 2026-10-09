import en from "../copy/en.json"

// All visible words (D76). Components read `copy.*`; templates with {name} go through format().
export const copy = en

export function format(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match
  )
}

const plural = new Intl.PluralRules("en")

export function pluralize(one: string, other: string, count: number): string {
  return format(plural.select(count) === "one" ? one : other, { count })
}

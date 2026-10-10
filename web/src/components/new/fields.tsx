import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Toggle } from "@/components/ui/toggle"
import { copy, format } from "@/lib/copy"
import type { AppConfig } from "@/lib/types"

// The /new form's sections (docs/UX.md §2 "/new"). Words from en.json, choices from /api/config.
const t = copy.form

function Section({ id, label, hint, children }: { id: string; label: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3" aria-labelledby={id}>
      <h2 id={id} className="text-lg font-semibold">
        {label}
        {hint && <span className="ml-2 text-sm font-normal text-muted-foreground">{hint}</span>}
      </h2>
      {children}
    </section>
  )
}

const STYLE_WORDS: Record<string, { label: string; description: string } | undefined> = copy.styles

export function StyleCards({ config, value, onChange }: { config: AppConfig; value: string; onChange: (key: string) => void }) {
  return (
    <Section id="style-heading" label={t.style.label} hint={t.style.required}>
      <RadioGroup value={value} onValueChange={onChange} aria-labelledby="style-heading">
        {config.styles.map((style) => {
          const words = STYLE_WORDS[style.key]
          if (words === undefined) {
            // A style the API knows but this build has no words for: leave it out, say so in the log.
            console.error("style from /api/config has no words in en.json", { style: style.key })
            return null
          }
          return (
            <RadioGroupItem key={style.key} value={style.key} className="flex flex-col gap-1 py-3">
              <span className="font-medium">{words.label}</span>
              <span className="text-sm text-muted-foreground">{words.description}</span>
            </RadioGroupItem>
          )
        })}
      </RadioGroup>
    </Section>
  )
}

export function LengthPicker({ config, value, onChange }: { config: AppConfig; value: number; onChange: (s: number) => void }) {
  return (
    <Section id="length-heading" label={t.length.label}>
      <RadioGroup
        value={String(value)}
        onValueChange={(v) => onChange(Number(v))}
        orientation="horizontal"
        aria-labelledby="length-heading"
        className="grid-flow-col"
      >
        {config.lengths_s.map((seconds) => (
          <RadioGroupItem key={seconds} value={String(seconds)} className="text-center">
            {format(t.length.option, { seconds })}
          </RadioGroupItem>
        ))}
      </RadioGroup>
      <p className="text-sm text-muted-foreground">{t.length.hint}</p>
    </Section>
  )
}

export function LanguagePicker({ config, value, onChange }: { config: AppConfig; value: string; onChange: (code: string) => void }) {
  const names: Record<string, string> = copy.textLanguages
  return (
    <Section id="lang-heading" label={t.textLanguage.label}>
      <RadioGroup value={value} onValueChange={onChange} orientation="horizontal" aria-labelledby="lang-heading" className="grid-flow-col">
        {config.text_languages.map((code) => (
          <RadioGroupItem key={code} value={code} className="text-center">
            {names[code] ?? code}
          </RadioGroupItem>
        ))}
      </RadioGroup>
    </Section>
  )
}

export function VoiceToggle({ available, checked, onChange }: { available: boolean; checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex min-h-target items-center justify-between gap-4">
        <Label htmlFor="keep-voice" className="text-lg font-semibold">
          {t.voice.label}
        </Label>
        <Switch id="keep-voice" checked={available && checked} disabled={!available} onCheckedChange={onChange} />
      </div>
      <p className="text-sm text-muted-foreground">
        {available ? (checked ? t.voice.on : t.voice.off) : t.voice.unavailable}
      </p>
    </section>
  )
}

export function Chips({ config, value, onChange }: { config: AppConfig; value: string[]; onChange: (chips: string[]) => void }) {
  const labels: Record<string, string> = copy.chips
  const toggle = (chip: string, on: boolean) => {
    if (!on) return onChange(value.filter((c) => c !== chip))
    // Chips in one exclusive group (Calm / Fast) replace each other.
    const rivals = config.chips.exclusive.filter((group) => group.includes(chip)).flat()
    onChange([...value.filter((c) => !rivals.includes(c)), chip])
  }
  return (
    <Section id="wishes-heading" label={t.wishes.label} hint={t.wishes.optional}>
      <div className="flex flex-wrap gap-2" role="group" aria-labelledby="wishes-heading">
        {config.chips.items.map((chip) => (
          <Toggle key={chip} pressed={value.includes(chip)} onPressedChange={(on) => toggle(chip, on)}>
            {labels[chip] ?? chip}
          </Toggle>
        ))}
      </div>
    </Section>
  )
}

export function NoteField({ max, value, onChange }: { max: number; value: string; onChange: (note: string) => void }) {
  return (
    <section className="flex flex-col gap-2">
      <Label htmlFor="note" className="text-lg font-semibold">
        {t.note.label}
        <span className="ml-2 text-sm font-normal text-muted-foreground">{t.note.optional}</span>
      </Label>
      <Textarea
        id="note"
        value={value}
        maxLength={max}
        placeholder={t.note.placeholder}
        aria-describedby="note-help note-count"
        onChange={(e) => onChange(e.target.value.slice(0, max))}
      />
      <p id="note-count" className="text-right text-sm text-muted-foreground">
        {format(t.note.counter, { count: value.length, max })}
      </p>
      <p id="note-help" className="text-sm text-muted-foreground">
        {t.note.help}
      </p>
    </section>
  )
}

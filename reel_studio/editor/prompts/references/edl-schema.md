# Cut list (EDL) format: the input of write_edl

`write_edl` validates it: errors come back with every violation and nothing is rendered; warnings
are craft risks. An accepted edit list is final, so avoid them before you call it, or say why in
the segment's `note`. Times are seconds. Clip ids come
from the brief (`c01`...).

```json
{
  "style": "recipe",
  "format": "recipe",
  "text_style": "outline",
  "defaults": {"rotate": 0, "zoom": 1.0, "focus_x": 0.5, "focus_y": 0.5},
  "grade": {"look": "warm", "strength": 0.6, "match": 0.8, "brightness": 0.02},
  "audio": {"natural_db": 0},
  "versions": [
    {
      "name": "A",
      "hook_text": "The crackly-top trick",
      "title_seconds": 2.5,
      "title_position": "top",
      "segments": [
        {"clip": "c24", "in": 7.0, "out": 9.0, "role": "hook", "beat": "hook",
         "note": "cracked tops, steam"},
        {"clip": "c02", "in": 3.0, "out": 6.6, "speed": 2.4, "role": "ingredient",
         "beat": "process", "text": "Brown the butter", "text_span": 2},
        {"clip": "c05", "in": 3.8, "out": 17.6, "speed": 7.0, "role": "ingredient",
         "beat": "process", "zoom": 1.3, "focus_y": 0.4},
        {"clip": "c24", "in": 5.4, "out": 7.0, "speed": 0.8, "role": "payoff", "beat": "payoff"}
      ]
    }
  ],
  "dropped": [{"clip": "c03", "reason": "blurred"}, {"clip": "c07", "reason": "same shot as c05"}],
  "preferences": [{"text": "Calm pace", "applied": true, "why": "longer holds on the pours"}],
  "caption": "Crackly-top brownies, one bowl\nBrown the butter first: that is the trick.\nDetails in the comments\n#brownies #baking",
  "music_hint": "warm lo-fi, mid tempo, strongest beat on the first cut",
  "assumptions": ["warm 0.6: brownies read golden, the cold rack shots match the board"],
  "check_by_eye": ["seg 3 may show a face at the left edge"]
}
```

## Top level
| Field | Default | Meaning |
|---|---|---|
| `style` | — | the order's style, copied from the brief; it must match |
| `format` | other | recipe, dessert, restaurant, product, compilation, asmr, pov, what-i-eat, food-fitness, other |
| `text_style` | outline | outline (white, dark edge, shadow, no box), box, plain |
| `defaults` | — | rotate / zoom / focus_x / focus_y applied to every segment unless it sets its own |
| `grade.look` | natural | natural, warm, moody, fresh, clean, reference (only when the brief offers style photos). See colour.md |
| `grade.strength` | 0.6 | 0..1, how much of the look |
| `grade.match` | 0.6 | 0..1, how strongly each clip is pulled to the set's exposure and white balance |
| `grade.brightness/contrast/saturation` | none | optional whole-Reel fine-tune after the look: -0.2..0.2, 0.7..1.4, 0.7..1.5 |
| `audio.natural_db` | 0 | overall level change of the natural sound. There is no music option. |
| `versions` | — | exactly one, named A. Text and clean are both rendered from it |
| `dropped` | — | every clip you did not use, with a plain reason ("blurred", "same shot as c04") |
| `preferences` | — | one entry per chip and per sentence of the customer's note: applied or not, and why |
| `caption` | — | the Instagram caption, at most 2,200 characters (template below); line breaks are real newlines in the JSON string, never an escaped backslash-n |
| `music_hint` | — | mood, tempo and where the strongest beat should land, at most 120 characters |
| `assumptions` | — | every default you used, and the look with its reason |
| `check_by_eye` | — | anything you were unsure about, for the person to look at |

## Version
| Field | Meaning |
|---|---|
| `hook_text` | opening text, up to about 6 words, shown 0 to `title_seconds` (2.5) at `title_position` |
| `segments` | ordered shots |

## Segment
| Field | Default | Meaning |
|---|---|---|
| `clip`, `in`, `out` | required | seconds inside the clip; `0 <= in < out <= duration` |
| `speed` | 1.0 | 0.25-8. Screen time = (out-in)/speed. Below 0.8 only on 60 fps clips |
| `role` | other | hook, setup, ingredient, process, mix, assembly, cook, bake, reveal, payoff, reaction, detail, ambience, verdict, other |
| `beat` | — | the purpose of this shot in the story, from your beat sheet |
| `text`, `text_span`, `text_position` | — | label (max 42 chars), how many segments it stays, top/center/low |
| `focus_x`, `focus_y`, `zoom`, `rotate` | from defaults | crop centre 0..1, zoom 1.0-2.0, rotate 0/180 |
| `fit` | crop | crop = fill 9:16 by cropping; blur = show the whole frame over a blurred copy (wide landscape shots: rooms, tables, signs) |
| `audio_db`, `mute` | 0, false | per-shot volume, or silence the shot |
| `allow_long` | false | lets a non-hook/payoff shot exceed 2.0 s; say why in `note` |
| `quote`, `visual_check` | — | speech only: the exact words kept, and whether the cut needs a look |
| `note` | — | your reason; copied into the timeline |

## Caption template
```
<first line = hook with search keywords>
<2-4 short lines: what it is, the key tip, the save reason>
<ingredients or prices ONLY if known; otherwise "Details in the comments">
<3-6 specific keywords or hashtags>
```
Plain English (or the order's text language), no emojis, readable on a phone.

## Outputs
Two files from the one version: with text, and clean (no text). 1080x1920, 30 fps, H.264, AAC,
-14 LUFS. The QA sheets made from them go to the critic, not to you.

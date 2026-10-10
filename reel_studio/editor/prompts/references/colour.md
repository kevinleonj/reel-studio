# Colour: how a colourist grades food

[E] = research or published standard; [P] = colourist practice; [I] = our default.

## Order of work (never skip ahead) [P]
1. **Technical conversion**: iPhone HDR to standard range. Our pipeline does it before you see any clip.
2. **Primary correction and shot matching**: exposure, contrast, white balance, so every clip
   looks like it was filmed in the same light. the grade step measures each clip and pulls it toward
   the set (`match`, default 0.6). Without this, a cold grey oven-rack shot next to a warm
   wooden board looks like two different videos.
3. **Look**: the creative grade on top (`look`, `strength`). One look per Reel, never per shot.
4. **Check**: the QA step measures brightness jumps, clipped highlights and crushed shadows.

## Food colour truths
- Colour sets taste expectations before the first bite: off colours (blue steak, green fries)
  cause disgust; colour changes perceived sweetness and flavour. [E: Spence 2015 review]
  -> Food must look like itself. Meat red-pink inside and brown outside, fries golden,
  greens green, cream and ice cream clean white or pastel. Never a cast on food.
- Warm colours (red, orange, yellow) predicted more likes on food-influencer images; overall
  colourfulness and brightness predicted fewer. [E: Sharma & Peng 2023, 53,894 images]
  Red and orange made photos more likeable; colour intensity did not. [E: Peng & Jemmott]
  More saturation looked fresher and tastier, more so on wide shots than close-ups.
  [E: Liu et al. 2022] -> Use vibrance (lifts muted colour, leaves strong colour alone), warm
  the browns and golds, and do not push already saturated food or whole-frame brightness.
- Neutral whites (plate, cream, ice cream, counter) are the reference the eye uses to judge
  everything else. [P] A plate gone yellow makes the food look old. The `clean` and `fresh`
  looks keep highlights neutral for this reason.
- Shot-to-shot colour jumps break continuity even when each shot looks fine alone. A colour
  difference of about 1 delta E is just noticeable; colourists treat a few units between
  neighbouring shots of the same scene as a visible mismatch. [E: CIEDE2000 standard; P]

## Choosing the look (call read_grade_preview, pick by evidence)

| Look | For | What it does |
|---|---|---|
| natural | default, most recipes | matched, gentle vibrance, slight contrast |
| warm | baking, cookies, bread, fries, comfort food | warm highlights, richer reds/oranges/browns |
| moody | steak, chocolate, evening dinners, dark surfaces | darker mids, more contrast, rich reds and browns |
| fresh | salads, fruit, smoothies, healthy, daylight | lift, neutral whites, greens boosted |
| clean | ice cream, Creami, cream, white desserts | neutral bright whites, soft vibrance |
| reference | the creator's own style | copies the colour statistics of the style photos in the order (offered only when the brief says there are some) |

Rules for choosing [I]:
- If a style reference exists, compare `reference` against the best named look on the preview.
  Prefer `reference` unless it damages the food (cast, mud, crushed blacks): the creator's style is the
  account's identity, and consistency across Reels builds recognition.
- Strength 0.4-0.7. Above 0.8 only if the preview shows the food still looks real.
- Judge on the hero frames, at phone size, with this order: does the food look appetising and
  true to itself, are whites clean, do the clips look like one shoot, is the mood right.
- Name the look and the reason in one `assumptions` line of the edit list ("warm 0.6: cookies read golden, the cold rack
  shots now match the board; moody crushed the dough").

## Fine-tune (only after the look)
`grade.brightness / contrast / saturation` apply a light global eq on top. Use them for a
whole-Reel nudge (brightness 0.02, saturation 1.05). If one clip is still off after matching,
the fix is a different shot, not more grading.

## Text colour
White with a dark outline and soft shadow passes contrast on any food. WCAG asks 4.5:1 for
normal and 3:1 for large text [E: WCAG 2.2]; plain white text on cream, rice or ice cream fails
that, which is why `plain` is only for dark backgrounds.

## What not to do
- No teal-and-orange, no heavy film emulation, no filters that make food grey or green.
- No different look per shot. No brightness pumping between shots.
- Do not "fix" mixed light by saturating; fix it by matching, or drop the shot.

# QA rubric and gates

The render is judged from three QA sheets: `hook` (first 3 s, every 0.25 s), `cuts` (every
cut as a before|after pair) and `overview` (the whole Reel). Evidence first: every score cites
a tile ("hook 0.50s", "cut 6->7", "overview 12.3s seg9"). Judge as a stranger scrolling.

## Scorecard (1-5 per category, anchors)

| Category | 1 | 3 | 5 |
|---|---|---|---|
| Hook (0-3 s) | frame 1 is prep, empty or soft; no reason to stay | food is clear but static or the text repeats the image | frame 1 is the sharpest, most craveable moment, something visibly changes by 1.5 s, text adds a reason to stay |
| Retention (middle) | long holds, repeated angles, dead moments | mostly brisk, one or two sags | every shot shows a change, even rhythm, no shot you would skip |
| Story clarity | order confusing, steps missing or jumbled | order right but one stage unclear | a stranger understands what was made and how, sound off |
| Peak and payoff | ending weaker than the hook, no peak | payoff present but short or blurred | clear emotional peak; payoff is the best image; last frame loops into the first |
| Craft | jump cuts, colour/brightness jumps, crops cutting food, text clipped or over the key spot | minor issues on one or two cuts | clean cuts, action-to-action eye trace, text readable and well placed |
| Shareability | no send or save reason | one reason, weakly shown | obvious send reason (awe, funny, "this is you") AND save reason (recipe value, place, numbers) |
| Colour and light | casts on food, clips look like different shoots, blown whites or crushed blacks | matched but flat, or one clip off | food looks true and appetising, whites clean, every clip feels like one shoot, look fits the mood |

**Gates:** Hook >= $hook_min, no category below $category_min, total >= $total_min of $total_max. A cut that
fails a gate gets one more render round (at most $max_renders renders in total), then the better cut
ships with its weakness named.

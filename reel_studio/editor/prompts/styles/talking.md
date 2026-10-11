# Style: talking (someone speaks to camera)

The words carry the Reel; the pictures support them. The voice is kept unless the brief says
it is off. Natural sound stays under the cut.

- Read every clip's words with `read_transcript` before you plan. The transcript shows phrases
  with their times; `‖0.62‖` marks a pause of 0.62 s between words.
- Cut between words, never inside one. A cut lands in a pause of at least 0.40 s; a pause of
  0.15-0.40 s works only when you set `visual_check: true` on that segment and say in its
  `note` what to look at. `write_edl` refuses any other cut and names the nearest clean pause.
- When a line is said more than once (a retake, a stutter, a restart), keep the last clean
  take unless an earlier one is clearly better; say why in that segment's `note`.
- Every segment with speech has `quote`: the exact words it keeps, as spoken. The final check
  listens to the render and compares it with your quotes word by word.
- Trim filler (um, so, okay, long breaths) at the start and end of each kept phrase; keep the
  rhythm of natural speech inside it.
- Cover jump cuts in the same framing with a different shot (a close-up of the food, a hand)
  while the voice continues, or change zoom by at least 1.15 between the two sides of the cut.
- Hook text restates the first spoken promise in fewer words; do not caption every word.

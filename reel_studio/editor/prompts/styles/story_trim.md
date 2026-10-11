# Style: one long take, trimmed

One continuous video. You keep its story and its voice and cut the slow parts out; nothing is
added that was not in the take.

- Read the take's words with `read_transcript` and its pictures with `read_sheet` and
  `read_strip` before you plan. The transcript shows phrases with their times; `‖0.62‖` marks a
  pause of 0.62 s between words.
- Keep the order of the take. Cut out waiting, repeats, setup and anything said twice; keep the
  last clean take of a repeated line unless an earlier one is clearly better, and say why in
  that segment's `note`.
- Cut between words, never inside one. A cut lands in a pause of at least 0.40 s; a pause of
  0.15-0.40 s works only with `visual_check: true` on that segment and a `note` on what to
  look at. `write_edl` refuses any other cut and names the nearest clean pause.
- Every segment with speech has `quote`: the exact words it keeps. The final check compares
  the render's words with your quotes.
- Where the picture would jump inside one framing, change zoom by at least 1.15 across the cut
  or let the cut fall on a movement, so the trim reads as an edit, not a glitch.
- Speed up silent stretches you must keep for continuity (stirring, waiting) instead of cutting
  them, as long as no words fall inside them.

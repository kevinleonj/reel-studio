# Editing craft: cutting, composition, montage, text, sound

[E] = research or established film practice; [P] = practitioner rule; [I] = our default.

## What a cut is for
Walter Murch's priorities when choosing a cut: emotion (51%), story (23%), rhythm (10%), eye
trace (7%), the 2D screen plane (5%), 3D space (4%). [E: "In the Blink of an Eye"] When two
choices compete, the one that serves the higher priority wins: a cut that keeps craving rising
beats a cut that is merely smooth.

## Montage
- **Metric and rhythmic montage** [E: Eisenstein]: metric = cuts at a steady length; rhythmic =
  cut length follows the movement inside the shots. Food Reels use metric for process (an even
  pulse that any song chosen later sits on) and rhythmic at peaks (let the pour or pull finish).
- **Graphic match** [E]: a round bowl cut to a round pan, a pour cut to a pour, a colour cut to
  the same colour. It turns a list of steps into a flow. Look for them on the cuts sheet: shape,
  position and dominant colour at the last frame of one shot and the first frame of the next.
  Use `focus_x/focus_y/zoom` to line the shapes up.
- **Match on action** [E]: cut in the middle of a motion and continue the motion in the next
  shot (lift the spoon -> spoon arrives at the mouth). The motion hides the cut.
- **Cut on action, mid-action** [P]: start a shot mid-motion; leave before the motion ends.
  One second of chopping says "chopping". Never cut mid-pour; show the whole pour sped up, or
  cut before it starts.
- **Jump cuts** [E: 30-degree rule]: two shots of the same subject from almost the same
  framing look like a glitch. Same clip, same zoom, close in time -> merge, insert a different
  shot, or change framing by zoom 0.2 or more. A fixed overhead camera across different steps
  is normal recipe style and fine.
- **Kuleshov** [E]: meaning comes from the sequence, not the single shot. A hand reaching back
  for a second croquette after the bite says "this is good" without text.

## Pacing
- Middle shots max 2.0 s on screen (enforced), most 0.7-1.5 s. [P; I]
- Even pulse in the middle: similar shot lengths, no random 0.3 s blips next to 2 s holds.
  Cuts under about 0.5 s only in deliberate rapid-fire runs. [P; E: gaze needs ~0.33 s to
  re-centre after a cut, Mital et al. 2011]
- Something must change on screen at least every 2-3 s. [P]
- Speed-ups compress process: speed = (out - in) / target screen time, typically 2-8x for
  mixing, whisking, chopping, waiting; 1x for drops, cracks, crunches (their sound sells them).
- Slow down only at peaks: hook and payoff 1.5-3 s; 0.5x only from 60 fps.
- The payoff runs slightly slower than the middle: the contrast feels like a reward.

## Composition in 9:16
- **Centre the subject.** People prefer the main object centred; the rule of thirds barely
  predicts aesthetic ratings. [E: Palmer lab 2008-2014; Amirshahi et al. 2014] In vertical
  video, centred subjects got longer fixations. [E, weak: Baig et al. 2025]
- **After every cut the eye goes to the centre** within about a third of a second, and motion
  is the strongest predictor of where people look; colour and brightness are near chance.
  [E: Mital, Smith, Hill & Henderson 2011] -> Put the action (the pour, the knife, the spoon),
  not the static dish, at the centre of each new shot. Choose `focus_x/focus_y` for the moving
  part.
- **Inward bias / lead room** [E: Palmer lab]: a subject moving or pointing sideways needs space
  in front of it. Shift the crop so the motion goes into the frame, not out of it.
- **Residual fixation** [E: Nielsen Norman Group 2017]: the eye stays where it was after a cut.
  For a smooth flow, start the next shot's action near where the last one ended (eye trace).
- **Fill the frame with food** for hooks, payoffs and textures (zoom 1.3-1.8). Wide shots only
  to orient (the table, the room, the full tray) and keep them short.
- **Shot size variety** [P]: alternate wide, medium and tight. Three wides in a row read flat.
- **Interface zones**: the top ~14% and bottom ~35% are covered by Instagram's buttons and
  caption. Keep the key action between 15% and 65% of the height.
- Hands enter from the bottom. Whole shoot upside down: `defaults.rotate: 180` once.
- Floor, tripod, phone, clutter at an edge: crop it with zoom 1.1-1.25 and a focus point.
- Landscape clips: pick the focus on the food; if the crop loses the subject (room, table,
  sign), use `fit: "blur"` for that context shot. Never for hook or payoff.

## Text
- Viewers looked at text overlays 82% of the time they were on screen. [E: NN/g 2017] Text
  steals attention from the food, so every word must earn its place.
- Hook text: up to 6 words, says what the image does not.
- On screen at least characters / 15 s and never under 0.85 s. [E: subtitle standard 17 cps]
- Labels 2-4 words, only where they add information (a step, an amount you saw, a place).
  Hold one label across related shots with `text_span`.
- Put text in empty space, upper-middle band (`top`), never over the key action; move it
  `low` or `center` when the action sits at the top. Gestalt proximity: text near what it
  names reads as belonging to it. [P]
- `outline` style (white, dark edge, soft shadow) reads on any food. Clean versions have no
  text at all.

## Sound (natural only, no music)
- Each segment's sound fades over 12 ms at its edges so cuts never click (render does it).
- Keep the sounds that sell texture at real speed: crunch, sizzle, crack, pour. [E: Zampini &
  Spence 2004]
- `audio_db` -6 to -12 to tame a harsh shot; `mute: true` for talking, TV or notifications.
  You cannot hear the footage: mute shots where the sheet suggests speech (a face mid-sentence,
  a person off-camera) and say so in the report.

## Ending and loop
- End on the payoff. The last frame should resemble the first so the replay feels continuous
  (the QA check measures a loop score). No fade to black, no end card.

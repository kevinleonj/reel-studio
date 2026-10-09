# UX — screens, words, states, tests

Locked with `docs/DECISIONS.md` v1. English only (D07). No accounts (D18), no cookies, no analytics
scripts (D20). Phone and laptop are both first-class (D17).

## 1. Goal and friction budget

- **Activation event:** a friend downloads or plays a finished Reel (`result_viewed_at` on the order).
- **Required answers before upload:** 2 — the style (one tap) and the invite code (typed). Everything
  else has a default: length 30 s, text language from the browser (`es*` → Spanish, else English),
  "Keep the voice?" from the style, no chips, no note.
- **Screens before value:** our form → Stripe's €0 confirmation (email) → upload → progress → result.
- Order links carry the token after `#` (D18): `/o/<order_id>#t=<token>`. Stripe's success redirect uses
  `?t=` and the page moves it behind `#` at once.
- Stripe's page stays because it collects the email, shows the €19 anchor and makes the later paid
  path identical (D58).

## 2. Screens

### `/` Landing
- Headline: **Turn your food clips into a Reel that's ready to post.**
- Line: "Upload up to 40 clips and photos. You get two edited versions and a caption by email."
- Button: **Start a Reel** → `/new`.
- Small print: "Invite-only beta: you need a code from Kevin." · "Edited by AI (Claude)." · Privacy · GitHub.
- No time promise anywhere until 10 cloud runs give a median (D16).

### Search and link previews (D71)
- `/` and `/privacy`: one `<h1>`, unique `<title>` and `<meta name="description">` from `web/src/copy/en.json`,
  canonical URL from `SITE_URL`, Open Graph and Twitter card tags with a 1200×630 image, `lang="en"`.
- `/new` and `/o/*`: `X-Robots-Tag: noindex` from the API plus the meta tag in the shell. They are not listed in
  robots.txt (a blocked page never shows its noindex, F69). `robots.txt` allows everything and names the sitemap.

### `/new` One form, one button at the end

| Section | Control | Default | Copy |
|---|---|---|---|
| What did you film? (required) | 5 cards, one choice | none | see table below |
| Length | Segmented 15 / 30 / 60 / 90 s | 30 s | "Most Reels that travel are under 60 s." |
| Text on the video | English / Spanish | from browser | — |
| Keep the voice? | Toggle | per style; follows the style until the user touches it; disabled with "Needs a Gemini key on this server" when none is set (D14) | On: "We transcribe the speech and cut between words." Off: "Natural sound only, no transcription." |
| Wishes (optional) | 6 chips, multi-select; Calm and Fast exclude each other | none | Start with the finished dish · Calm pace · Fast pace · Show every step · No text over faces · End on the first bite |
| Anything we should know? (optional) | Text area, counter `0/200`, hard stop at 200 | empty | Placeholder: "e.g. It's my grandma's pistachio cheesecake. Keep the shot where I pour the sauce." Under it: "Works: the dish's name, a shot to keep or skip, where to start or end. Doesn't work: music (add it in Instagram), logos, effects, footage you didn't upload." |
| Invite code (required) | Text input, `autocapitalize=characters`, `autocomplete=off` | empty | Hidden when `PAYMENTS=off` (your own laptop) |
| Email (only when `PAYMENTS=off`) | Optional email input | empty | "Optional: we email you when it's ready." (goes to Mailpit locally) |
| Button | **Continue** | disabled until style and code are set | Loading: "Opening checkout…" |

Style cards (text only, D08):

| Card | Description line |
|---|---|
| Quick clips, no talking | Many short shots. We pick the best moments and cut a fast montage. |
| Recipe | From ingredients to the finished dish, step by step. |
| One long video | One continuous take. We cut the slow parts and keep the story. |
| Someone talking | Clips of a person speaking to camera. We keep the best take of each line. |
| Tutorial | Someone shows and explains how to do something. |

Errors on Continue (shown under the code field, form keeps every value):

| API answer | Message |
|---|---|
| `code_invalid` | "This code doesn't work. Check it, or ask Kevin for a new one." |
| `code_inactive` (expired or used up) | "This code has expired. Ask Kevin for a new one." |
| `week_full` | "This week's Reels are all taken. Places free up on Monday." |
| `rate_limited` | "Too many tries. Wait a minute and try again." |
| network or 5xx | "We couldn't reach the server. Check your connection and try again." |

### Stripe Checkout (hosted)
€19.00, discount −€19.00, total €0.00, email field. **Cancel** returns to `/new?cancel=<order_id>&t=<token>`:
the page asks the API to expire that checkout (place released at once) and refills the form from the
order's settings. Nothing is kept in the browser.

### `/o/<order_id>#t=<token>` The order page (one page, driven by `status`)

| Status | What the page shows |
|---|---|
| `awaiting_payment` | "Confirming your code…" The page calls `POST /api/orders/<id>/fulfil` once, then polls. |
| `paid` | **Upload.** "Add your clips and photos" · "Up to 40 files, 4 GB in total, 20 minutes per video." · **Choose files** (`accept="video/*,image/*"`, multiple; opens the gallery on phones) · one row per file: name, size, progress bar, state (waiting, uploading 43%, done, failed + Retry) · total line "1.2 GB of 4 GB · 12 of 40 files" · on phones: "Keep this page open until the uploads finish." · **Start editing** enabled when at least one file is done and none is uploading or failed · **Add more files** |
| `queued` | "Waiting for a free editor. 1 Reel ahead of you." · "You can close this page. We'll email k•••@gmail.com when it's ready." |
| `running` | Stage list (below): done stages ticked, the current one with elapsed minutes, later ones grey · the same close-the-page line |
| `done` | **Result** (below) |
| `failed` | The plain message for its error code from `docs/EDITOR.md` §10 and the retry it offers there (**Start again** → `/new` refilled, or **Try with fewer clips**, or none) · "Kevin has been notified." |
| `paused` | "We hit this month's budget. Your Reel is saved and starts when it resets. We'll email you." |
| `expired` | "This checkout expired before it was confirmed." · **Start again** |
| `abandoned` | "This order was never started, so its clips were deleted." · **Start again** |
| `deleted` | "Your files are deleted." |
| bad id or token | "This link doesn't work. Use the link in the email we sent you." |

Upload behaviour (the part most likely to break, tested first, D17):
- Files go straight to Cloud Storage through resumable sessions created by the API in one batch call
  (`POST /api/orders/<id>/uploads` with every file's name, size and type). Limits are checked on the
  batch: 40 files, 4 GB, allowed types.
- Chunks of 8 MiB (a multiple of 256 KiB). A failed chunk asks the session for its offset and resumes
  from there, up to 5 tries with backoff.
- After a page reload, finished files are listed again (`GET /api/orders/<id>/files`); an unfinished
  file must be chosen again and restarts from zero.
- Two files upload at a time.

Upload errors (shown above the file list):

| API answer | Message |
|---|---|
| `too_many_files` | "That's more than 40 files. Remove some and try again." |
| `too_large` | "That's more than 4 GB in total. Remove a few long videos." |
| `bad_type` | "<file name> isn't a video or photo we can use (MP4, MOV, JPEG, PNG)." |
| `no_files` | "Add at least one clip first." |

Videos over 20 minutes are accepted by the upload and then left out by the editor, listed under
"What we left out" (D10).

Stage list (names from `docs/EDITOR.md` §1):

| Stage key | Shown as |
|---|---|
| `reading` | Reading your clips |
| `listening` | Listening (only with voice on) |
| `planning` | Planning the edit |
| `rendering` | Cutting and colour |
| `checking` | Final checks |
| `revising` | Improving the cut (only if it happens) |
| `saving` | Saving your Reel |

Polling: `GET /api/orders/<id>` every 5 s while visible, and at once on `visibilitychange` to
visible (D16). Updates are announced in an `aria-live="polite"` region.

### Result (status `done`)
1. Two players: **With text** and **Clean** (side by side on a laptop, stacked on a phone). Each has
   **Download** (signed link with `Content-Disposition: attachment`).
2. **Caption** with **Copy**.
3. **Text to add in Instagram** (for the clean version): time and words per line.
4. **Music:** the mood and tempo hint. "Pick the track in Instagram."
5. **What we left out:** each dropped file and why.
6. **Your wishes:** each chip and note sentence, applied or not, with the reason.
7. **Check before posting:** the editor's doubts, then "Edited by AI (Claude). Check it before posting." (D21)
8. **How did we do?** 1–5 buttons, optional comment, **Send**.
9. **Delete my files now** → inline confirm "Delete the Reels and your clips? This can't be undone." **Delete** / **Keep** (never a browser dialog).
10. "Files are deleted automatically after 30 days."

## 3. Emails (Resend in the cloud, Mailpit locally)

Plain HTML that works as text, under 100 KB, no tracking pixels.

| Email | Subject | Body | Sent by |
|---|---|---|---|
| Link | Your Reel Studio link | Button **Upload your clips** · "Up to 40 files, 4 GB." · "Keep this email: the link is your access." | reel-api after payment |
| Ready | Your Reel is ready: "<hook text>" | Button **Watch and download** · "Files are deleted after 30 days." · AI line | reel-editor |
| Failed | Your Reel didn't finish | The plain message · "Your code still works." · **Start again** | reel-editor or sweep |
| Paused | Your Reel is waiting | The paused message | reel-editor |
| To Kevin | `[reel-studio] <status> <order_id> at <stage>: <code>` | Plain text with the order link for `reelctl` | reel-editor, sweep |

From: `Reel Studio <reels@reels.limeralda.com>` (D56).

## 4. Look and feel

- Tokens (colour, type scale, spacing, radius) defined once in Tailwind's theme; shadcn/ui components
  only; one accent colour; light and dark follow the system.
- Feel like: Stripe Checkout (calm, one action per screen) and the iOS share sheet (big, obvious
  targets). Must not feel like: an "AI startup" landing page (gradients, glow, sparkle icons) or the
  cream-and-serif template look.
- WCAG 2.2 AA: text contrast ≥ 4.5:1, targets ≥ 44×44 px, visible focus, every input labelled,
  reduced motion respected.
- Speed budget on the built site (Lighthouse in `make prerelease`, mobile profile): Largest Contentful Paint ≤ 2.5 s,
  Interaction to Next Paint ≤ 200 ms, Cumulative Layout Shift ≤ 0.1.

## 5. Measurement: events now, analytics off (D75)

Funnel from order timestamps (always on): `created_at` → `paid_at` → first object in `in/` → `queued_at` →
`finished_at` → `result_viewed_at` → `feedback.at`. `reelctl report` prints the counts per week and
per style, cost per Reel and the mean critic total.

Analytics contract. The web code calls `track()` at these points from day one; with analytics off it does
nothing and loads nothing. Turning it on = `GA4_MEASUREMENT_ID` (and later `GOOGLE_ADS_ID`) in settings,
the consent banner, and the Google hosts in the Content Security Policy.

| Event | Fires when | Parameters | Never sent |
|---|---|---|---|
| `page_view` | each page load | `page_location` = route template (`/`, `/new`, `/o/:id`, `/privacy`) | real `/o/` path, `#t=` token |
| `generate_lead` | `/new` form submitted | `style`, `length` | email |
| `begin_checkout` | redirect to Stripe starts | `value`, `currency` from `/api/config` | code |
| `purchase` | order page first sees `paid` | `transaction_id` = SHA-256 of the order id (first 16 hex), `value`, `currency` | order id |
| `upload_complete` | all files uploaded | `file_count`, `total_mb` (rounded) | file names |
| `reel_ready` | page first sees `done` | `style`, `duration_s` | — |
| `reel_download` | a download button pressed | `version` (`text` or `clean`) | signed URL |
| `feedback_sent` | rating stored | `rating` | comment |

Consent (F70): `gtag('consent','default',…)` with all four types `denied` runs before anything else;
basic mode, so the Google tag script loads only after "Accept"; "Reject" is one tap, same size.
Acceptance test (STEP-06, analytics off): a page load makes no request to any Google host.

## 6. Acceptance tests (Playwright, `tests/e2e/`, phone 390×844 and laptop 1280×800)

1. Happy path with `PAYMENTS=off` and the fake editor: choose style → defaults shown → code → order
   page → upload 3 fixture files → Start → stages advance → result shows both players, Copy works.
2. **Most likely failure:** a chunk upload is dropped mid-file (route interception) and the file still
   finishes by resuming from the server offset.
3. The note stops at 200 characters; Calm and Fast cannot both be selected.
4. Changing the style flips the voice toggle until the user touches it, then never again.
5. `week_full`, `code_invalid` and `rate_limited` show their messages and keep the form values.
6. A wrong token shows the "link doesn't work" page and no order data.
7. Delete my files: confirm inline, status becomes `deleted`, players disappear.
8. axe-core finds no serious or critical violations in any state above.
9. Manual, once per release, on a real iPhone with Safari: upload a 300 MB HEVC `.mov` from the
   gallery over mobile data; record the result in `HANDOFF.md`.

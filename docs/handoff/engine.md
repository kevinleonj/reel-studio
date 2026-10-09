# Handoff — lane engine

Written by the engine lane only. Newest entry on top.

## Status board
- Done: STEP-02 phase A (kit inventory, `config/media.toml`, port plan below)
- Partly: STEP-02 (phase B, the package code, waits for STEP-01's skeleton: `pyproject.toml`, `reel_studio/core/ports.py`, `config.py`)
- Blocked: the `prepare` luma test (see Needs Kevin 1)
- Not started: STEP-02 phase B; STEP-03 onward
- Next: when STEP-01 merges, `git merge origin/main`, then write the failing tests below in the order given

## Needs Kevin
1. **STEP-02 asks for "mean luma inside the kit's range" for the tonemapped HDR proxy. The kit has
   no such range.** Searched `scripts/`, `tests/`, `references/colour.md`, `README.md`, `CLAUDE.md`:
   the only related evidence is the comment at `prep.py:40-41` (npl=203 came out about 25 % darker
   than npl=100). Proposal: render the synthetic HLG clip and the same `testsrc2` pattern encoded
   SDR, and require the proxy's mean luma (0-255) within ±15 % of the SDR render's. The reviewer
   measured the unchanged kit (Homebrew ffmpeg-full 9.0.2, not yet the Debian image): SDR 126.9,
   HDR npl=100/mobius 111.7 (−12.0 %), npl=203 94.2 (−25.8 %); ±10 % would fail the kit itself.
   A new threshold, so it needs your yes; the test stays `xfail(strict=True)` until then.
4. **I wrote into the old kit by accident.** `$OLD_KIT_DIR/.ruff_cache/` (3 cache files, 21:44:00)
   was created by the post-edit ruff hook while this session's shell sat in the kit directory.
   No kit source changed (snapshot of 2,651 files, `__pycache__` and `.env*` excluded, identical),
   but the snapshot was taken 4 s after that cache appeared, so it does not prove the cache away.
   I did not delete it (that would be another write there). To restore: `rm -rf "$OLD_KIT_DIR/.ruff_cache"`.
5. **EDITOR.md §1 says tonemap "zscale + hable"; the kit uses mobius** (`prep.py:45`,
   `media.toml [prepare.tonemap]`). The port keeps mobius per D46. Correct EDITOR §1, or say hable is wanted.
6. **Dependencies the lane cannot add.** STEP-01's `[editor]` extra lists anthropic, google-genai,
   pillow only; `pyproject.toml`/`uv.lock` are outside this lane. Phase B needs numpy 2.5.3,
   opencv-python-headless 5.0.0.93 (no libGL in slim), scenedetect 0.7.1; pillow-heif 1.8.0 only if
   HEIC is accepted (`limits.toml` allowed_types has none). Versions confirmed on PyPI by the reviewer.
7. **ffmpeg path setting.** Claude Code's PATH hides keg-only `ffmpeg-full`, so `settings.py` gets
   `ffmpeg_path`/`ffprobe_path` without defaults; you set absolute paths in `.env` (I cannot), and
   phase B adds the names to `.env.example`. Fonts: Poppins-Bold.ttf + OFL.txt ship as package data
   under `reel_studio/editor/media/fonts/`, no host-font fallbacks.
2. **Contact sheets: the kit algorithm must change (STOP rule of STEP-02, failing case written here
   first).** Kit `prep.py:167-221` (`build_sheets`) draws a flow layout on 1980×1980 sheets with
   340 px rows and 2-8 evenly spaced frames per clip. D38 (locked) requires 4×4 tiles of 384×216 =
   1536×864, 2-6 frames per clip at scene changes, a tile → clip/time legend and near-duplicates
   removed. Failing case: `test_sheet_is_1536x864_with_16_tiles` fails against a port of
   `build_sheets` (its sheet is 1980 px wide). Plan: new `sheets.py` per D38, reusing the kit's scene
   detection (`prep.py:119-122`) for frame times and the kit's SSIM (`qa.py:43-51`) with
   `[qa].near_same_ssim = 0.93` (`qa.py:31`) as the near-duplicate threshold. Reusing that kit
   threshold for a new purpose is my choice, not a kit fact; say if you want a separate value.
3. Three lines in `config/media.toml` carry `hardcode-ok (config home)`: the global hardcode hook
   flagged `limiter_headroom_db`, `limiter_oversample_hz`, `limiter_release_ms` in the config file
   itself (a false positive: config is their home). I used the hook's own marker rather than adding
   a root `.hardcode-allowlist` outside this lane. Say if you prefer the allowlist.

## Evidence lines (the gates read these)

## Log

### 2026-10-09 — STEP-02 phase A: inventory and port plan (no package code)

Before: no `config/media.toml`, no plan. After: `config/media.toml` (249 kit values, each with unit
and `file.py:line`), this plan. The old kit was only read; proof at the end.

#### A. Kit inventory (`$OLD_KIT_DIR/scripts/`, 10 files, 1,751 lines)

| Kit file | Functions | ffmpeg / external calls | Constants (where they go) |
|---|---|---|---|
| `common.py` (173) | `slug`, `KitError`, `log`, `_brew_tool`, `find_tool`, `ffmpeg`, `ffprobe`, `has_filter`, `run`, `probe`, `is_hdr`, `font_path`, `main_guard` | `ffmpeg -hide_banner -filters` (:93); `ffprobe -v error -print_format json -show_streams -show_format` (:107) | `OUT_W/H/FPS` 1080/1920/30 (:19) and `SAFE` 65/1015/270/1250 (:24) → `constants.py` (D43, Meta safe zone); `VIDEO_EXT`, `IMAGE_EXT`, `SKIP_NAMES` (:26-29) → `constants.py`; HDR transfers `arib-std-b67`, `smpte2084` (:151) → `constants.py`; stderr tail 15 (:101), probe error 300 chars (:111) → `[tools]`; Homebrew paths, `REEL_FFMPEG` env (:49, :62) → `settings.py` `ffmpeg_path`, `ffprobe_path` with no default: the image (D72) has Debian ffmpeg on `PATH`, the Mac sets the Homebrew `ffmpeg-full` path in `.env`; the Homebrew lookup is not ported |
| `prep.py` (306) | `tonemap_chain`, `sort_key`, `cover_size`, `make_proxy`, `photo_proxy`, `detect_cuts`, `split_windows`, `frame_at`, `colourfulness`, `measure`, `build_sheets`, `main` | proxy: `-vf [tonemap],scale=W:H:flags=lanczos,fps=N,format=yuv420p,setsar=1 -c:v libx264 -crf 17 -preset veryfast -g fps -color_* bt709 -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest -movflags +faststart`, plus `-f lavfi anullsrc=r=48000:cl=stereo` when silent (:78-85); tonemap `zscale=tin=…:pin=bt2020:min=bt2020nc:t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p` (:46-47); photo `-loop 1 -framerate 30 -t 3` + `zoompan=z='1+0.06*on/N'…` (:106-112); PySceneDetect `detect(AdaptiveDetector(min_scene_len="0.6s"))` (:121); OpenCV seeks (:132) | `[prepare]`, `[prepare.tonemap]`, `[prepare.photo]`, `[measure]`; `ROW_H`, `SHEET_W/H` (:32-33) dropped with `build_sheets` (Needs Kevin 2); Hasler-Süsstrunk 0.3 (:141) → `constants.py` (formula) |
| `grade.py` (277) | `frame_stats`, `merge`, `reference_stats`, `_lab`, `_rgb`, `correction_params`, `apply_transform`, `write_cube`, `set_stats_of`, `grade_config`, `build_luts`, `hero_frames`, `main` (preview sheet) | none (writes `.cube` files read by `lut3d`) | `[grade]`, `[grade.stats]`, `[grade.match]`, `[grade.look_common]`, `[grade.looks.*]`, `[grade.preview]`; `LOOKS` (:31) → EDL enum |
| `render.py` (380) | `seg_get`, `seg_dur`, `validate`, `crop_filter`, `grade_filter`, `atempo_chain`, `text_events`, `render_segment`, `measure_loudness`, `finalize`, `main` | segment (:239-245): `-ss in -t len -i proxy` + crop/blur chain, `lut3d=…:interp=tetrahedral`, `eq`, `setpts`, `fps=30`; audio `asetpts,atempo…,volume,aresample=48000,apad,atrim,afade` → `libx264 -crf 12 -preset superfast`, `pcm_s16le` `.mkv`; loudness pass 1 (:252-257) `concat … loudnorm=I=-14:TP=-1:LRA=11:print_format=json -f null`; final (:271-303) concat + PNG `overlay enable=between(t,…)`, loudnorm `linear=true` pass 2 or `volume,aresample=192000,alimiter=limit=0.8:attack=1:release=50:level=false,aresample=48000`, `libx264 -preset medium -crf 18 -profile:v high -r 30 -g 60 -maxrate 20M -bufsize 40M`, `aac -b:a 128k -ar 48000 -ac 2 -movflags +faststart` | `[edl]`, `[edl.format_target_s]`, `[edl.defaults]`, `[render.*]`; `ROLES`, `LONG_OK` (:30-32) and the role sets at :135, :150 → EDL enums; -14 LUFS (:257, :287) → `constants.py` (D42); `FORMATS` short-cut ranges (:33-37, second tuple) unused in the kit, not ported |
| `qa.py` (244) | `grab`, `ssim`, `stats`, `measure_audio`, `tile`, `grid`, `qa_version`, `main` | `ebur128=peak=true`; `blackdetect=d=0.2:pix_th=0.08,freezedetect=n=0.003:d=1.0` `-f null` (:67-69) | `[qa]`, `[qa.sampling]`, `[qa.sheets]`; SSIM c1/c2 0.01/0.03 (:45) → `constants.py` (Wang et al. 2004) |
| `textcards.py` (88) | `_wrap`, `render_card` | none (Pillow) | `[text]`; `STYLES` (:17), positions (:57-64) → EDL enums |
| `strip.py` (73) | `main` (filmstrip) | none (OpenCV, Pillow) | `[strip]`; 2000 px (:67) → `limits.toml [sheets].max_image_side_px` (F08) |
| `shots.py` (40) | `main` (prints the clip/window table) | none | none |
| `selftest.py` (97) | `make_inputs`, `edl_for`, `main` | HDR: `testsrc2=s=1920x1080:r=30:d=4` + `sine=f=440:d=4`, `zscale=…t=arib-std-b67:p=bt2020:m=bt2020nc,format=yuv420p10le`, `libx265 -tag:v hvc1`, colour tags, then `-display_rotation:v:0 90 -c copy` (:30-37); 60 fps `testsrc2=s=1080x1920:r=60` + `sine=f=660`, 5 s (:41-42); landscape `1920x1080:r=30`, 4 s, no audio (:43-44); long take `testsrc` 6 s + `smptehdbars` 8 s concat + `sine=f=330:d=14` (:45-48); photo 1200×1600 (:49); style photo `_VSCO.jpg` (:50) | fixture parameters stay in `tests/fixtures/make_clips.py` (tests are not product config) |
| `status.py` (73) | `media`, `state`, `main` | `has_filter` | `STALE_DAYS` 180 (:19); not ported (kit folder states; the product has orders) |

Kit dependencies (`requirements.txt`, pinned 7 Oct 2026): `scenedetect==0.7.1`, `opencv-python==5.0.0.93`,
`numpy==2.5.3`, `pillow==12.3.0`, `pillow-heif==1.8.0` (`claude-agent-sdk` is not ported, D30).
Phase B adds them to the `editor` extra with one HANDOFF line each; `opencv-python-headless` instead
of `opencv-python` for the slim image (no libGL), to confirm from the PyPI page before adding.

#### B. Module map → `reel_studio/editor/media/`, and the first failing test of each

Order is the build order. `unit` = `tests/unit/editor/` (no ffmpeg, fakes only); `integ` =
`tests/integration/editor/` (real ffmpeg on the session fixtures). Each module also gets the
empty / one / many / failure cases (craft rules); only the first test is listed.

| # | New module | From kit | First failing test (written and seen failing before code) |
|---|---|---|---|
| 0 | `tests/fixtures/make_clips.py` + session fixture | `selftest.py:25-51` | integ `test_fixtures_have_expected_streams`: five clips + one photo; HDR clip probes `arib-std-b67`, rotation 90; 60 fps clip; landscape without audio; long take 90 s (STEP-02, the kit's is 14 s) with a hard cut; JPEG still |
| 1 | `tools.py` (ffmpeg port adapter: `run`, `probe`, `has_filter`, `is_hdr`) | `common.py:56-151` | integ `test_probe_swaps_size_for_rotated_clip`: the HDR fixture probes as 1080×1920 portrait. unit `test_run_error_keeps_last_15_stderr_lines` with the fake runner. Raises `RenderError`/`NoUsableInput` (EDITOR §10) instead of `KitError`; no `print`, JSON log per call with `latency_ms` (D74) |
| 2 | `prepare.py` (`cover_size`, `make_proxy`, `photo_proxy`, `tonemap_chain`, `sort_key`, discovery) | `prep.py:37-115, 225-275` | integ `test_hdr_proxy_is_sdr_bt709_cover_1080x1920`: proxy `color_transfer=bt709`, `pix_fmt=yuv420p`, covers 1080×1920. Then: 60 fps → 60, 30 → 30; silent clip gains a stereo track; photo → 3 s clip with audio; the work-folder copy of the original is gone once its proxy exists, one file at a time (new: the kit reads inputs in place); luma check (Needs Kevin 1) |
| 3 | `measure.py` (`detect_cuts`, `split_windows`, `frame_at`, `colourfulness`, `measure`, clip colour stats) | `prep.py:119-163, 276-290` | unit `test_split_windows_caps_at_24_and_covers_range`; integ `test_long_take_cut_detected` (cut at the fixture's join ± 0.1 s) |
| 4 | `sheets.py` (new, D38) | replaces `prep.py:167-221` | unit `test_sheet_is_1536x864_with_16_tiles` on synthetic numpy frames; then 2-6 frames per clip, legend tile → (clip, t), near-duplicates dropped |
| 5 | `strip.py` | `strip.py:24-69` | integ `test_strip_of_long_take_fits_2000px` (90 s range, 30 frames, both sides ≤ `max_image_side_px`, F08); end clamped to duration |
| 6 | `grade.py` (stats, match, looks, `.cube`, preview) | `grade.py:37-271` | unit `test_strength_0_match_0_is_identity` (`apply_transform` returns its input within 5e-3: the float32 RGB→Lab→RGB round trip alone deviates 3.41e-3, measured on the kit by the reviewer); `test_cube_has_33_cubed_rows_red_fastest`; preview ≤ 2000 px (F08) |
| 7 | `textcards.py` | `textcards.py:21-88` | unit `test_long_label_shrinks_inside_safe_zone` (42-char label: ≤ 3 lines, `inside_safe_zone` true) |
| 8 | `edl.py` (Pydantic v2 models + `check(edl, shots) -> Report`) | `render.py:42-163`, `edl-schema.md` | unit `test_check_returns_every_violation`: an EDL with three independent errors yields three errors, not one. Then `audio.music` refused, v1 fields, warnings kept separate from errors |
| 9 | `render.py` (`crop_filter`, `grade_filter`, `atempo_chain`, `text_events`, `render_segment`, `measure_loudness`, `finalize`, `render_both`) | `render.py:167-376` | unit `test_atempo_chain_8x_is_three_stages` (`atempo=2.0,atempo=2.0,atempo=2.0000`); integ `test_render_basic_outputs_text_and_clean` (both 1080×1920, 30/1, h264, aac, −14 ± 1 LUFS); refuses `audio.music` before any ffmpeg call |
| 10 | `qa.py` (hard checks + hook/cuts/overview sheets + `qa.json`) | `qa.py:37-226` | integ `test_qa_hard_checks_all_true_on_basic_render`; unit `test_hard_check_values_are_bools`. `hard_checks` keys = the kit's PASS/FAIL lines: `spec_text`, `spec_clean`, `size_duration_text`, `size_duration_clean`, `no_black_frames`, `text_in_safe_zone`. The kit emits one safe-zone line per text box (`qa.py:200-201`); here `text_in_safe_zone` = every box inside, true when there is no text. Loudness stays PASS-or-FLAG as in the kit (`qa.py:113-115`), not a hard check: the gate enforces −14 ± 1 LUFS itself (`scripts/gates/step02.py`). The rest stay flags |
| 11 | `shots.py` (`format_table(shots) -> str`) | `shots.py:18-36` | unit `test_table_lists_every_clip_and_window` (feeds STEP-03's tool result) |
| 12 | `reel_studio/cli/reel.py` `reel render --edl <file> <folder> [--out]` | `render.py:306-376`, `qa.py:229-240` | integ `test_input_folder_byte_identical_after_render` (D02: sha256 of every input file before and after); outputs `text.mp4`, `clean.mp4`, `qa.json` in `--out` |
| 13 | `docker/editor.Dockerfile`, `make image-editor` | — | `slow` test: `reel render` inside the image on the fixtures (CI) |

Every value comes from `config/media.toml`, `config/limits.toml` or `reel_studio/core/constants.py`
(loaded once, validated at start-up). Phase B adds to `constants.py`, each with its source comment:
`OUT_W, OUT_H, OUT_FPS` (D43), `TARGET_LUFS = -14` (D42), `AUDIO_RATE_HZ = 48000`, `AUDIO_CHANNELS = 2`,
`SAFE_ZONE` (`common.py:21-24`), `VIDEO_EXT`, `IMAGE_EXT`, `SKIP_NAMES`, `HDR_TRANSFERS`, the
Hasler-Süsstrunk 0.3 and SSIM c1/c2 coefficients, the `.cube` header lines (`grade.py:172`).
Each ffmpeg filter and option used gets a `docs/FACTS.md` row from ffmpeg-filters documentation.

#### C. EDL schema (`edl.py`): kit fields unchanged (D46) + v1 fields (EDITOR §7)

Kit top level (`edl-schema.md:32-43`, `render.py:51-77`):

| Field | Type | Default | Rule |
|---|---|---|---|
| `format` | enum: recipe, dessert, restaurant, product, compilation, asmr, pov, what-i-eat, food-fitness, other | other | error if unknown; length outside `[edl.format_target_s]` → warning |
| `text_style` | enum: outline, box, plain | outline | error if unknown |
| `defaults` | `{rotate, zoom, focus_x, focus_y, fit}` | — | segment value wins (`render.py:42-43`) |
| `grade` | `{look, strength, match, brightness?, contrast?, saturation?}` | natural, 0.6, 0.6 | look ∈ natural/warm/moody/fresh/clean/reference; strength, match 0..1; fine-tune −0.2..0.2, 0.7..1.4, 0.7..1.5 |
| `audio` | `{natural_db}`; `music` forbidden | natural_db 0 | `audio.music` present → error (D02, D42) |
| `versions` | list of Version | — | exactly 1; names unique, `[A-Za-z0-9]+` |

Version (`edl-schema.md:45-49`): `name`; `hook_text` (alias `title`, `render.py:152`); `title_seconds`
(2.5); `title_position` (top/center/low, default top); `segments` (non-empty). Warnings: first role
not hook, hook > 3.5 s, hook > 7 words, > 9 labels, last role not payoff/verdict/reveal, jump-cut risk.

Segment (`edl-schema.md:51-62`): `clip` (known id), `in`, `out` (`0 ≤ in < out ≤ duration + 0.01`),
`speed` (1.0; 0.25-8; < 0.8 only on ≥ 50 fps), `role` (15-value enum, default other), `text` (≤ 42),
`text_span` (1), `text_position` (top/center/low), `focus_x`, `focus_y` (0..1), `zoom` (1.0-2.0),
`rotate` (0/180), `fit` (crop/blur), `audio_db` (0), `mute` (false), `allow_long` (false), `note`.
Errors: on-screen < 0.25 s; non-hook/reveal/payoff/verdict/reaction > 2.0 s without `allow_long`;
total outside 3-90 s. Warnings: nearly static, blurry (from measured windows).

v1 additions (EDITOR §7):

| Field | Type | Rule |
|---|---|---|
| `style` | enum from `config/styles.toml` keys: montage, recipe, long_take, talking, tutorial | must equal the order's style (checked when an order is given; `reel render` passes none) |
| `dropped` | list of `{clip, reason}` | `clip` known; every input not in a segment appears once |
| `preferences` | list of `{text, applied: bool, why}` | one per chip and note sentence (checked in STEP-03 where the order exists) |
| `caption` | string | ≤ 2,200 chars |
| `music_hint` | string | ≤ 120 chars |
| `assumptions` | list of strings | — |
| `check_by_eye` | list of strings | — |
| Segment `beat` | string | purpose in the story |
| Segment `quote` | string | speech only: exact words kept |
| Segment `visual_check` | bool | speech only |

Open for phase B: whether the v1 fields are required in hand-written EDLs. Proposal: optional in the
model, required by the loop's `write_edl` check (STEP-03), so `tests/fixtures/edl/basic.json` can stay
close to the kit's selftest EDL (`selftest.py:54-71`). Length limits go to a new `config/limits.toml`
`[edl]` table, `caption_max_chars = 2200` and `music_hint_max_chars = 120`, citing EDITOR §7, not into code.

Validation design: Pydantic collects every field error in one `ValidationError`; the cross-field and
shots-dependent rules run in `check(edl, shots)`, which appends to a list instead of returning at the
first problem, and returns `Report(errors, warnings)` (the kit mixed `continue` after some errors,
`render.py:95, 99, 103`; those skips stay, since later rules need valid in/out/speed).

#### D. Evidence

- `config/media.toml` parses (tomllib: 10 tables). A checker matched each value against its cited
  kit line: 249 values checked, 1 manual (`center_offset_px = -100`, kit writes `- 100` at
  `textcards.py:60`).
- Old kit unchanged: file list, sizes, mtimes and sha256 (files < 50 MB) snapshotted before reading
  and compared after writing: identical (2,651 files; `.env*` skipped by rule, never read).

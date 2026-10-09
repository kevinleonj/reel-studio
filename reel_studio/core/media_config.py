"""Strict models for config/media.toml: the kit's media tunables (D46, D76).

Field names mirror the TOML keys one to one, and each key's comment in the TOML names its kit
file and line. Values are floats, not Decimal: they feed pixel and audio maths, not money.
"""

from pydantic import BaseModel, ConfigDict

type Pair = tuple[int, int]
type Rgb = tuple[int, int, int]
type Rgba = tuple[int, int, int, int]
type Lab3 = tuple[float, float, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Tools(_Strict):
    error_tail_lines: int
    probe_error_chars: int
    run_timeout_s: int
    probe_timeout_s: int


class Tonemap(_Strict):
    npl: int
    algorithm: str
    desat: int
    sdr_luma_tolerance: float


class Photo(_Strict):
    seconds: float
    fps: int
    push_in: float
    supersample: int
    crf: int
    preset: str
    gop_frames: int


class Prepare(_Strict):
    high_fps_threshold: int
    proxy_fps_high: int
    proxy_fps_low: int
    scale_flags: str
    video_codec: str
    crf: int
    preset: str
    gop_seconds: int
    audio_codec: str
    audio_bitrate_kbps: int
    silent_track_layout: str
    tonemap: Tonemap
    photo: Photo


class Measure(_Strict):
    scene_min_len_s: float
    window_s: float
    max_windows_per_clip: int
    min_window_s: float
    sample_spacing_s: float
    samples_min: int
    samples_max: int
    edge_inset_s: float
    thumb_long_px: int
    thumb_short_px: int
    colour_samples: int
    colour_edge_s: float
    colour_min_end_s: float


class Strip(_Strict):
    max_frames: int
    min_frames: int
    frame_step_s: float
    end_inset_s: float
    cols: int
    thumb_w_px: int
    gap_px: int
    label_h_px: int
    jpeg_quality: int


class GradeStats(_Strict):
    thumb_w_px: int
    percentiles: tuple[float, float, float]
    neutral_chroma_max: float
    neutral_l_min: float
    neutral_l_max: float
    neutral_min_pixels: int
    clip_hi_l: float
    crush_l: float


class GradeMatch(_Strict):
    min_clip_range_l: float
    set_p98_cap_l: float
    contrast_k_min: float
    contrast_k_max: float
    neutral_frac_min: float
    set_warmth_kept: float
    protect_chroma: float
    protect_weight_min: float


class LookCommon(_Strict):
    vibrance_chroma: float
    contrast_pivot_l: float
    warm_hue_below_deg: float
    warm_hue_above_deg: float
    highlight_start_l: float
    highlight_span_l: float


class Natural(_Strict):
    vibrance: float
    contrast: float


class Warm(_Strict):
    vibrance: float
    warm_hue_gain: float
    contrast: float
    b_lift: float
    a_lift: float


class Moody(_Strict):
    warm_hue_gain: float
    other_hue_gain: float
    gamma: float
    contrast: float
    b_lift: float
    b_lift_start_l: float
    b_lift_span_l: float


class Fresh(_Strict):
    vibrance: float
    green_hue_min_deg: float
    green_hue_max_deg: float
    green_hue_gain: float
    l_lift: float
    highlight_desat: float


class Clean(_Strict):
    vibrance: float
    l_lift: float
    contrast: float
    highlight_desat: float


class Reference(_Strict):
    fallback_vibrance: float
    max_mean_shift: Lab3
    std_ratio_min: Lab3
    std_ratio_max: Lab3
    min_std: float


class Looks(_Strict):
    natural: Natural
    warm: Warm
    moody: Moody
    fresh: Fresh
    clean: Clean
    reference: Reference


class GradePreview(_Strict):
    hero_frames: int
    tile_w_px: int
    tile_h_px: int
    jpeg_quality: int


class Grade(_Strict):
    lut_size: int
    reference_words: tuple[str, ...]
    default_look: str
    default_strength: float
    default_match: float
    lut_interp: str
    stats: GradeStats
    match: GradeMatch
    look_common: LookCommon
    looks: Looks
    preview: GradePreview


class EdlDefaults(_Strict):
    speed: float
    zoom: float
    focus: float
    title_seconds: float
    text_span: int


class Edl(_Strict):
    min_segment_s: float
    min_speed: float
    max_speed: float
    max_middle_s: float
    max_middle_tolerance_s: float
    slow_motion_below: float
    slow_motion_min_fps: int
    out_tolerance_s: float
    zoom_min: float
    zoom_max: float
    label_max_chars: int
    total_min_s: float
    total_max_s: float
    hook_max_s: float
    hook_max_words: int
    labels_max: int
    jump_cut_gap_s: float
    static_motion_ratio: float
    static_min_s: float
    blur_ratio: float
    brightness_min: float
    brightness_max: float
    contrast_min: float
    contrast_max: float
    saturation_min: float
    saturation_max: float
    format_target_s: dict[str, Pair]
    defaults: EdlDefaults


class TextTiming(_Strict):
    min_event_s: float


class Segment(_Strict):
    crf: int
    preset: str
    audio_codec: str
    mute_db: float
    fade_s: float
    atempo_max: float
    atempo_min: float


class BlurFit(_Strict):
    boxblur: str
    background_brightness: float


class Loudness(_Strict):
    true_peak_db: float
    lra: int
    silence_below_lufs: float
    limiter_headroom_db: float
    max_gain_db: float
    limiter_oversample_hz: int
    limiter_limit: float
    limiter_attack_ms: int
    limiter_release_ms: int


class Final(_Strict):
    preset: str
    crf: int
    profile: str
    gop_seconds: int
    maxrate: str
    bufsize: str
    audio_bitrate_kbps: int


class Render(_Strict):
    text_timing: TextTiming
    segment: Segment
    blur_fit: BlurFit
    loudness: Loudness
    final: Final


class Text(_Strict):
    title_px: int
    step_px: int
    min_px: int
    shrink_step_px: int
    max_lines: int
    pad_x_px: int
    pad_y_px: int
    line_gap_px: int
    box_radius_px: int
    box_alpha: int
    top_offset_px: int
    center_offset_px: int
    stroke_min_px: int
    stroke_divisor: int
    shadow_alpha: int
    shadow_dx_px: int
    shadow_dy_px: int
    shadow_extra_stroke_px: int
    shadow_blur_px: int
    fill_rgba: Rgba
    outline_rgba: Rgba


class QaSampling(_Strict):
    segment_half_span_s: float
    segment_end_inset_s: float
    cut_before_s: float
    cut_after_s: float
    hook_offset_s: float
    first_frame_s: float
    last_frame_inset_s: float
    overview_edge_s: float


class QaSheets(_Strict):
    hook_seconds: float
    hook_step_s: float
    hook_cols: int
    hook_tile_px: Pair
    cuts_cols: int
    cuts_tile_px: Pair
    overview_frames: int
    overview_cols: int
    overview_tile_px: Pair
    gap_px: int
    label_h_px: int
    jpeg_quality: int


class Qa(_Strict):
    max_file_mb: float
    fps_tolerance: float
    lufs_min: float
    lufs_max: float
    black_min_s: float
    black_pixel_threshold: float
    freeze_noise: float
    freeze_min_s: float
    jump_ssim: float
    jump_hist: float
    near_same_ssim: float
    luma_jump: float
    dead_ratio: float
    dead_min_s: float
    blur_ratio: float
    blown_pixel: int
    blown_frac: float
    crushed_pixel: int
    crushed_frac: float
    colour_shift_de: float
    colour_shift_gap_s: float
    first_frame_soft_ratio: float
    first_frame_dark_luma: float
    read_chars_per_s: float
    read_min_s: float
    read_tolerance_s: float
    thumb_w_px: int
    thumb_h_px: int
    hsv_bins: Pair
    ssim_window: int
    ssim_sigma: float
    sampling: QaSampling
    sheets: QaSheets


class SheetStyle(_Strict):
    font_px: int
    background_rgb: Rgb
    label_rgb: Rgb
    safe_zone_outline_rgb: Rgb


class Media(_Strict):
    tools: Tools
    prepare: Prepare
    measure: Measure
    strip: Strip
    grade: Grade
    edl: Edl
    render: Render
    text: Text
    qa: Qa
    sheet_style: SheetStyle

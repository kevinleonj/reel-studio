"""Format constants: values fixed by a file format or a vendor, not tunables (D76).

Every constant carries a source comment on its line or the line above, with a docs/FACTS.md id
when the value comes from a vendor. Tunables belong in config/*.toml, deployment values in
reel_studio/settings.py.
"""

# ---------------------------------------------------------------- output (D43, D42)

OUT_W = 1080  # Reel frame width, 9:16 (D43; kit common.py:19)
OUT_H = 1920  # Reel frame height (D43; kit common.py:19)
OUT_FPS = 30  # output frame rate (D43; kit common.py:19)
TARGET_LUFS = -14.0  # integrated loudness target, LUFS (D42; kit render.py:257)
AUDIO_RATE_HZ = 48000  # every intermediate and final file (kit prep.py:84, render.py:245,302)
AUDIO_CHANNELS = 2  # stereo everywhere (kit prep.py:84, render.py:245,302)
# Text safe zone on 1080x1920: 270 px clear at the top, 670 px at the bottom, 65 px each side
# (kit common.py:21-24, third-party figures derived from Meta's ad placement guidance).
SAFE_X0 = 65  # kit common.py:24
SAFE_X1 = 1015  # kit common.py:24
SAFE_Y0 = 270  # kit common.py:24
SAFE_Y1 = 1250  # kit common.py:24

# ---------------------------------------------------------------- inputs

# Video container extensions ffmpeg reads (kit common.py:26-27).
VIDEO_EXT = frozenset(
    {
        ".mov",
        ".mp4",
        ".m4v",
        ".hevc",
        ".mkv",
        ".avi",
        ".webm",
        ".mts",
        ".m2ts",
        ".3gp",
        ".mpg",
        ".mpeg",
        ".ts",
        ".wmv",
        ".flv",
    }
)
IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".heic", ".webp"})  # stills (kit common.py:28)
SKIP_NAMES = frozenset({"brief.md", "brief.txt", ".ds_store"})  # never footage (common.py:29)
# ffprobe color_transfer names of HDR video, HLG and PQ (kit common.py:151; ITU-R BT.2100).
HDR_TRANSFERS = frozenset({"arib-std-b67", "smpte2084"})
QUARTER_TURN_DEG = 90  # |rotation| mod 180 == 90 swaps width and height (kit common.py:131)
HALF_TURN_DEG = 180  # a half turn keeps width and height (kit common.py:131)

# ---------------------------------------------------------------- pixel and colour maths

U8_MAX = 255  # 8-bit channel maximum (uint8 images in OpenCV and Pillow)
LAB_L_MAX = 100.0  # OpenCV float Lab L range 0..100 for float32 input in 0..1 (F202)
FULL_TURN_DEG = 360.0  # hue angles are degrees on a circle (kit grade.py:112)
HSV_HUE_RANGE = (0, 180)  # OpenCV 8-bit HSV hue histogram range (kit qa.py:63)
HSV_SAT_RANGE = (0, 256)  # OpenCV 8-bit HSV saturation histogram range (kit qa.py:63)
COLOURFULNESS_MEAN_WEIGHT = 0.3  # Hasler & Suesstrunk (2003) (kit prep.py:141, qa.py:61)
SSIM_K1 = 0.01  # Wang et al. (2004) SSIM stabiliser K1 (kit qa.py:45)
SSIM_K2 = 0.03  # Wang et al. (2004) SSIM stabiliser K2 (kit qa.py:45)
MS_PER_S = 1000  # milliseconds per second
BYTES_PER_MB = 1_000_000  # decimal megabytes, as the kit reports file sizes (kit qa.py:109-110)
SECONDS_DECIMALS = 3  # durations rounded to whole milliseconds (kit prep.py:271)
COLOUR_CHANNELS = 3  # three-channel images: BGR, RGB and Lab pixels

# ---------------------------------------------------------------- website and API (STEP-06, 07)

# Random identifiers (ARCHITECTURE.md §4, D18): bytes from secrets.token_hex / token_urlsafe.
ORDER_ID_BYTES = 16  # 32 hex characters
LINK_TOKEN_BYTES = 32  # the order link's access token, 256 bits; only its SHA-256 is stored
RUN_TOKEN_BYTES = 16  # queue.run_token checked by the worker before it starts
SECONDS_PER_MINUTE = 60  # unit conversion for signed-link lifetimes (minutes in config)
UPLOAD_SESSION_BYTES = 24  # laptop upload session ids, like the cloud's unguessable session URLs
EMAIL_MAX_BYTES = 100_000  # docs/UX.md §3: every email under 100 KB
BYTES_PER_MIB = (
    1024 * 1024
)  # config/limits.toml upload.chunk_mib is in MiB (a multiple of 256 KiB, F307)
BYTES_PER_GB = 1_000_000_000  # config/limits.toml max_total_bytes is decimal: 4 GB = 4,000,000,000
ASSET_MAX_AGE_S = 31_536_000  # one year: hashed /_astro/* files are immutable (ARCHITECTURE.md §7)
EMAIL_ADDRESS_MAX_CHARS = 254  # RFC 5321 §4.5.3.1.3: longest forward path, minus the angle brackets
INVITE_CODE_MAX_CHARS = 64  # Stripe promotion codes are shorter; this only bounds the request body
UPLOAD_SESSION_ID_MAX_CHARS = (
    128  # bounds the id in a path; ids are 32 chars (UPLOAD_SESSION_BYTES)
)
FILE_NAME_MAX_CHARS = 255  # APFS and ext4 name limit: a longer name could not be stored

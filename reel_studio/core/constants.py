"""Format constants: values fixed by a file format or a vendor, not tunables (D76).

Every constant carries a source comment on its line or the line above, with a docs/FACTS.md id
when the value comes from a vendor. Tunables belong in config/*.toml, deployment values in
reel_studio/settings.py.
"""

MS_PER_SECOND = 1000  # unit conversion for the latency_ms log field (D74)
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

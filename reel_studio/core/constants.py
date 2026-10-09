"""Format constants: values fixed by a file format or a vendor, not tunables (D76).

Every constant carries a source comment on its line or the line above, with a docs/FACTS.md id
when the value comes from a vendor. Tunables belong in config/*.toml, deployment values in
reel_studio/settings.py.
"""

MS_PER_SECOND = 1000  # unit conversion for the D74 `latency_ms` log field

# OAuth scope for signing download URLs through IAM signBlob (F34; doc ledger: google-auth)
GOOGLE_CLOUD_PLATFORM_SCOPE = (
    "https://www.googleapis.com/auth/cloud-platform"  # hardcode-ok: protocol constant
)

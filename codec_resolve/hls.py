"""
HLS SUPPLEMENTAL-CODECS brand definitions (RFC 8216bis §4.4.6.2).

ISOBMFF compatibility brands registered at MP4RA, used in Apple HLS
to signal backward-compatible fallback formats for enhanced codecs.
"""
from dataclasses import dataclass
from typing import Optional


# ════════════════════════════════════════════════════════════════════
# HLS SUPPLEMENTAL-CODECS Brand Table (MP4RA Registered Brands)
# ════════════════════════════════════════════════════════════════════
# RFC 8216bis §4.4.6.2: SUPPLEMENTAL-CODECS value is a slash-separated
# list of fields. The first field is the codec format; remaining fields
# are ISOBMFF compatibility brands registered at MP4RA.
#
# The brand tells the player what backward-compatible fallback format
# the base layer conforms to, WITHOUT parsing the init segment.
#
# Source: MP4RA brand registry + Apple WWDC 2024 + draft-pantos-hls-rfc8216bis-19
#
# For DV Profile 8 (HEVC-based), the brand disambiguates the sub-profile
# that is normally hidden inside the RPU's bl_signal_compatibility_id:
#   db1p → compat_id 1 (HDR10/PQ cross-compatible)
#   db2g → compat_id 2 (SDR cross-compatible)
#   db4h → compat_id 4 (HLG cross-compatible)
#
# For DV Profile 10 (AV1-based), same principle:
#   db1p → Profile 10.1 (HDR10/SDR cross-compatible), VIDEO-RANGE=PQ
#   db4h → Profile 10.4 (HLG cross-compatible), VIDEO-RANGE=HLG

@dataclass
class HLSBrand:
    """ISOBMFF compatibility brand used in HLS SUPPLEMENTAL-CODECS."""
    brand: str                     # 4-char FourCC ("db1p", "db4h", etc.)
    description: str               # Human-readable meaning
    spec_owner: str                # "Dolby", "Samsung/Panasonic", etc.
    inferred_compat_id: Optional[int]  # bl_signal_compatibility_id (for DV P8)
    video_range: Optional[str]     # Expected VIDEO-RANGE ("PQ", "HLG", "SDR")
    dv_profiles: set               # DV profiles this brand applies to


HLS_DV_BRANDS = {
    # ── Dolby Vision brands ──
    "db1p": HLSBrand(
        brand="db1p",
        description="Dolby Vision cross-compatible with HDR10 (PQ)",
        spec_owner="Dolby",
        inferred_compat_id=1,      # bl_signal_compatibility_id=1 (HDR10/PQ)
        video_range="PQ",
        dv_profiles={8, 10}),      # P8.1, P10.1

    "db2g": HLSBrand(
        brand="db2g",
        description="Dolby Vision cross-compatible with SDR (BT.1886)",
        spec_owner="Dolby",
        inferred_compat_id=2,      # bl_signal_compatibility_id=2 (SDR)
        video_range="SDR",
        dv_profiles={8, 10}),      # P8.2, P10.2

    "db4h": HLSBrand(
        brand="db4h",
        description="Dolby Vision cross-compatible with HLG (VUI=14)",
        spec_owner="Dolby",
        inferred_compat_id=4,      # bl_signal_compatibility_id=4 (HLG)
        video_range="HLG",
        dv_profiles={8, 10}),      # P8.4, P10.4

    # ── Non-DV enhancement brands (informational, not DV-specific) ──
    "cdm4": HLSBrand(
        brand="cdm4",
        description="HDR10+ dynamic metadata (Samsung/Panasonic)",
        spec_owner="Samsung/Panasonic",
        inferred_compat_id=None,   # Not a DV brand
        video_range="PQ",
        dv_profiles=set()),        # HDR10+, not DV
}



"""
Codec entry point registry.

Maps ISOBMFF FourCC entry points to their codec family and capabilities.
Single source of truth for all dispatch logic across resolve, decode, and CLI.
"""

# Maps codec entry points to their family and capabilities
CODEC_ENTRIES = {
    "hvc1": {"family": "hevc", "base_codec": "HEVC", "is_dv": False},
    "hev1": {"family": "hevc", "base_codec": "HEVC", "is_dv": False},
    "av01": {"family": "av1",  "base_codec": "AV1",  "is_dv": False},
    "vp09": {"family": "vp9",  "base_codec": "VP9",  "is_dv": False},
    "dvhe": {"family": "dv",   "base_codec": "HEVC", "is_dv": True},
    "dvh1": {"family": "dv",   "base_codec": "HEVC", "is_dv": True},
    "dvav": {"family": "dv",   "base_codec": "AVC",  "is_dv": True},
    "dva1": {"family": "dv",   "base_codec": "AVC",  "is_dv": True},
    "dav1": {"family": "dv",   "base_codec": "AV1",  "is_dv": True},
    # Non-standard DV entries (edge cases, Profile 5 only)
    "dvc1": {"family": "dv",   "base_codec": "HEVC", "is_dv": True},
    "dvhp": {"family": "dv",   "base_codec": "HEVC", "is_dv": True},
    # Legacy (bare tag, no structured codec string)
    "vp8":  {"family": "vp8",  "base_codec": "VP8",  "is_dv": False},
}

# CLI aliases: human-friendly names → list of entry points
ENTRY_ALIASES = {
    "hevc":   ["hvc1", "hev1"],
    "av1":    ["av01"],
    "vp9":    ["vp09"],
    "dv":     ["dvhe", "dvh1", "dvc1", "dvhp"],
    "dv-avc": ["dvav", "dva1"],
    "dv-av1": ["dav1"],
    "vp8":    ["vp8"],
    "all":    ["hvc1", "hev1", "av01", "vp09", "dvhe", "dvh1"],
}

ALL_ENTRIES = set(CODEC_ENTRIES.keys())

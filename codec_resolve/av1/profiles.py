"""
AV1 profile definitions and selection logic.

Source: AV1 Bitstream & Decoding Process Specification §6.4.1,
        AV1 Codec ISO Media File Format Binding §5.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Set
from ..models import Content, Chroma


# ── Profile definitions ─────────────────────────────────────────────

@dataclass
class AV1ProfileDef:
    seq_profile: int
    name: str
    max_bit_depth: int           # 10 for P0/P1, 12 for P2
    allowed_chroma: Set[Chroma]
    mono_allowed: bool
    note: str


_420 = {Chroma.YUV420}
_420_444 = {Chroma.YUV420, Chroma.YUV444}
_ALL_CHROMA = {Chroma.YUV420, Chroma.YUV422, Chroma.YUV444}

AV1_PROFILE_DEFS: Dict[int, AV1ProfileDef] = {
    0: AV1ProfileDef(
        seq_profile=0, name="Main",
        max_bit_depth=10,
        allowed_chroma=_420,
        mono_allowed=True,
        note="8/10-bit, 4:2:0 only. Monochrome allowed. "
             "Standard consumer profile (streaming, browsers)"),
    1: AV1ProfileDef(
        seq_profile=1, name="High",
        max_bit_depth=10,
        allowed_chroma=_420_444,
        mono_allowed=False,
        note="8/10-bit, 4:2:0 + 4:4:4. Monochrome NOT allowed. "
             "Used for high-quality 4:4:4 content"),
    2: AV1ProfileDef(
        seq_profile=2, name="Professional",
        max_bit_depth=12,
        allowed_chroma=_ALL_CHROMA,
        mono_allowed=True,
        note="8/10/12-bit, all chroma formats. "
             "Broadcast and professional mastering"),
}

AV1_PROFILE_NAMES = {p.seq_profile: p.name for p in AV1_PROFILE_DEFS.values()}


# ── Bit depth derivation ────────────────────────────────────────────
# AV1 spec: BitDepth depends on seq_profile, high_bitdepth, twelve_bit.
# In the codec string, bitDepth is explicit (DD field), so we just validate.

VALID_BIT_DEPTHS = {
    0: {8, 10},       # Main: high_bitdepth=0→8, =1→10
    1: {8, 10},       # High: same
    2: {8, 10, 12},   # Professional: adds twelve_bit→12
}


# ── Chroma subsampling codes ────────────────────────────────────────
# CCC field in codec string: three digits = subsampling_x, subsampling_y,
#   chroma_sample_position.
# Mapping to our Chroma enum:

CHROMA_FROM_SUBSAMPLING = {
    (1, 1): Chroma.YUV420,   # CCC = 110, 111, 112, 113 (first two digits)
    (1, 0): Chroma.YUV422,   # CCC = 100, 101, 102, 103
    (0, 0): Chroma.YUV444,   # CCC = 000, 001, 002, 003
}

SUBSAMPLING_FROM_CHROMA = {
    Chroma.YUV420: (1, 1),
    Chroma.YUV422: (1, 0),
    Chroma.YUV444: (0, 0),
    Chroma.MONO:   (1, 1),   # mono uses 4:2:0 subsampling values
}

CHROMA_SAMPLE_POSITION_NAMES = {
    0: "Unknown (CSP_UNKNOWN)",
    1: "Vertical (CSP_VERTICAL / MPEG-2 co-sited)",
    2: "Colocated (CSP_COLOCATED / MPEG-4 top-left)",
    3: "Reserved",
}


# ── Profile selection (forward resolve) ─────────────────────────────

def resolve_av1_profile(c: Content) -> int:
    """Select the minimum AV1 profile that supports the content."""
    if c.bit_depth > 10:
        return 2  # Professional — only profile with 12-bit
    if c.chroma == Chroma.YUV422:
        return 2  # Professional — only profile with 4:2:2
    if c.chroma == Chroma.YUV444:
        return 1  # High — 4:4:4 requires at least High
    # 4:2:0 or mono, ≤10-bit → Main
    return 0


# ── BitrateProfileFactor ────────────────────────────────────────────
# AV1 spec Annex A: effective max bitrate scales with profile.
BITRATE_PROFILE_FACTOR = {0: 1.0, 1: 2.0, 2: 3.0}


# ── Codec string formatting ─────────────────────────────────────────

def format_av1_string(profile: int, level_idx: int, tier: int,
                      bit_depth: int, monochrome: int,
                      subsampling_x: int, subsampling_y: int,
                      chroma_sample_position: int,
                      color_primaries: int,
                      transfer_characteristics: int,
                      matrix_coefficients: int,
                      video_full_range_flag: int) -> str:
    """Format a complete AV1 codec string (always full 10-field form)."""
    tier_char = "M" if tier == 0 else "H"
    return (f"av01.{profile}.{level_idx:02d}{tier_char}.{bit_depth:02d}"
            f".{monochrome}"
            f".{subsampling_x}{subsampling_y}{chroma_sample_position}"
            f".{color_primaries:02d}.{transfer_characteristics:02d}"
            f".{matrix_coefficients:02d}.{video_full_range_flag}")

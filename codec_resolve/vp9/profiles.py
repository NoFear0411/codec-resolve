"""
VP9 profile definitions and selection logic.

Source: VP9 Bitstream Specification §7.2,
        VP Codec ISO Media File Format Binding §5.

Profile selection is orthogonal on two axes:
  - Bit depth:  P0/P1 = 8-bit,  P2/P3 = 10/12-bit
  - Chroma:     P0/P2 = 4:2:0,  P1/P3 = 4:2:2 or 4:4:4

Formula: profile = (depth > 8 ? 2 : 0) + (chroma != 4:2:0 ? 1 : 0)
"""
from dataclasses import dataclass
from typing import Dict, Optional, Set
from ..models import Content, Chroma


# ── Profile definitions ─────────────────────────────────────────────

@dataclass
class VP9ProfileDef:
    profile: int
    name: str
    bit_depths: Set[int]          # {8} for P0/P1, {10, 12} for P2/P3
    allowed_chroma: Set[Chroma]
    note: str


_420 = {Chroma.YUV420}
_NON_420 = {Chroma.YUV422, Chroma.YUV444}

VP9_PROFILE_DEFS: Dict[int, VP9ProfileDef] = {
    0: VP9ProfileDef(
        profile=0, name="Profile 0",
        bit_depths={8},
        allowed_chroma=_420,
        note="8-bit, 4:2:0 only. Standard consumer profile "
             "(streaming, browsers)"),
    1: VP9ProfileDef(
        profile=1, name="Profile 1",
        bit_depths={8},
        allowed_chroma=_NON_420,
        note="8-bit, 4:2:2 or 4:4:4. High-quality chroma"),
    2: VP9ProfileDef(
        profile=2, name="Profile 2",
        bit_depths={10, 12},
        allowed_chroma=_420,
        note="10/12-bit, 4:2:0 only. HDR10 and HLG content"),
    3: VP9ProfileDef(
        profile=3, name="Profile 3",
        bit_depths={10, 12},
        allowed_chroma=_NON_420,
        note="10/12-bit, 4:2:2 or 4:4:4. Professional mastering"),
}

VP9_PROFILE_NAMES = {p.profile: p.name for p in VP9_PROFILE_DEFS.values()}


# ── Chroma subsampling codes ────────────────────────────────────────
# CC field in VP9 codec string: 2-digit integer (00–03).
# 00/01 both encode 4:2:0 — they differ only in chroma sample position.
# Source: VP Codec ISO Media File Format Binding §4.

CHROMA_FROM_CC = {
    0: Chroma.YUV420,   # chroma_sample_position = 0 (vertical / left)
    1: Chroma.YUV420,   # chroma_sample_position = 1 (colocated / top-left)
    2: Chroma.YUV422,
    3: Chroma.YUV444,
}

CC_FROM_CHROMA = {
    Chroma.YUV420: 1,   # default: colocated (modern standard)
    Chroma.YUV422: 2,
    Chroma.YUV444: 3,
}

CHROMA_SAMPLE_POSITION_NAMES = {
    0: "Vertical (left)",
    1: "Colocated (top-left)",
}

# Valid CC values per profile (decoder uses this for VP9_CHROMA_INVALID)
VALID_CC_FOR_PROFILE = {
    0: {0, 1},     # P0: 4:2:0 only
    1: {2, 3},     # P1: 4:2:2 or 4:4:4
    2: {0, 1},     # P2: 4:2:0 only
    3: {2, 3},     # P3: 4:2:2 or 4:4:4
}


# ── Profile selection (forward resolve) ─────────────────────────────

def resolve_vp9_profile(c: Content) -> int:
    """Select the VP9 profile from content parameters.

    Two orthogonal axes:
      - Bit depth: P0/P1 = 8-bit, P2/P3 = high bit depth (10/12)
      - Chroma:    P0/P2 = 4:2:0, P1/P3 = non-4:2:0 (4:2:2 or 4:4:4)

    Formula: profile = (depth > 8 ? 2 : 0) + (chroma != 4:2:0 ? 1 : 0)
    """
    depth_axis = 2 if c.bit_depth > 8 else 0
    chroma_axis = 1 if c.chroma not in (Chroma.YUV420, Chroma.MONO) else 0
    return depth_axis + chroma_axis


# ── Codec string formatting ─────────────────────────────────────────

def format_vp9_string(profile: int, level_value: int, bit_depth: int,
                      chroma_subsampling: Optional[int] = None,
                      color_primaries: Optional[int] = None,
                      transfer_characteristics: Optional[int] = None,
                      matrix_coefficients: Optional[int] = None,
                      video_full_range_flag: Optional[int] = None) -> str:
    """Format a VP9 codec string. All fields are 2-digit zero-padded.

    Short form (mandatory fields only):
        vp09.PP.LL.DD

    Full form (all fields — optional group must be complete):
        vp09.PP.LL.DD.CC.cp.tc.mc.FF
    """
    base = f"vp09.{profile:02d}.{level_value:02d}.{bit_depth:02d}"

    if chroma_subsampling is None:
        return base

    return (f"{base}"
            f".{chroma_subsampling:02d}"
            f".{color_primaries:02d}"
            f".{transfer_characteristics:02d}"
            f".{matrix_coefficients:02d}"
            f".{video_full_range_flag:02d}")

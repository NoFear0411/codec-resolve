"""
HEVC profile definitions, selection logic, and codec string formatting.

Source: ITU-T H.265 Annex A + ISO/IEC 14496-15 Annex E.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from ..models import Content, Chroma, Transfer, Gamut, Scan, Tier, ConstraintStyle
from .levels import HEVCLevel


@dataclass
class HEVCProfileDef:
    """Static profile definition from the spec."""
    idc: int
    name: str
    max_depth: int                        # Maximum bit depth
    chroma_set: set                       # Supported Chroma enum values
    compat_bits: set                      # Profile IDCs for backward-compatibility
    auto_select: bool = False             # Eligible for auto-detection?
    note: str = ""

# Chroma groupings
_420 = {Chroma.YUV420}
_444 = {Chroma.YUV444}
_ALL = {Chroma.YUV420, Chroma.YUV422, Chroma.YUV444, Chroma.MONO}

HEVC_PROFILE_DEFS: Dict[int, HEVCProfileDef] = {
    1:  HEVCProfileDef(1,  "Main",                     8,  _420, {1, 2},
                       auto_select=True),
    2:  HEVCProfileDef(2,  "Main 10",                  10, _420, {2},
                       auto_select=True),
    3:  HEVCProfileDef(3,  "Main Still Picture",        8,  _420, {1, 2, 3},
                       note="Single-frame profile (HEIF, thumbnails)"),
    4:  HEVCProfileDef(4,  "Range Extensions",          16, _ALL, {4},
                       auto_select=True,
                       note="Sub-profiles: Main 4:2:2, Main 4:4:4, "
                            "Monochrome, 12/14/16-bit, etc."),
    5:  HEVCProfileDef(5,  "High Throughput",           16, _444, {5},
                       note="Intra-only 4:4:4, studio editing/mastering"),
    6:  HEVCProfileDef(6,  "Multiview Main",            8,  _420, {1, 2, 6},
                       note="Stereo 3D, two texture views"),
    7:  HEVCProfileDef(7,  "Scalable Main",             8,  _420, {1, 2, 7},
                       note="SHVC spatial/SNR/temporal scalability"),
    8:  HEVCProfileDef(8,  "Scalable Main 10",          10, _420, {2, 8},
                       note="SHVC with 10-bit base layer"),
    9:  HEVCProfileDef(9,  "Screen Content Coding",     8,  _420, {1, 9},
                       note="IBC + palette mode for screen capture"),
    10: HEVCProfileDef(10, "Screen Content Coding 10",  10, _420, {2, 10},
                       note="SCC with 10-bit support"),
    11: HEVCProfileDef(11, "High Throughput SCC",       16, _444, {5, 11},
                       note="Intra SCC for studio screen content"),
    12: HEVCProfileDef(12, "Scalable Range Extensions", 16, _ALL, {4, 12},
                       note="SHVC + RExt capabilities"),
    13: HEVCProfileDef(13, "Multiview Range Extensions",16, _ALL, {4, 13},
                       note="Multiview + RExt capabilities"),
}


# =============================================================================
# HEVC PROFILE SELECTION (ITU-T H.265 Annex A)
# =============================================================================

@dataclass
class HEVCProfile:
    """Resolved HEVC profile with all fields determined."""
    idc: int
    name: str
    profile_space: int = 0
    compat_flags: int = 0      # 32-bit compatibility flags

    # Constraint flag values (all deterministic once profile + content known)
    general_progressive: int = 1
    general_interlaced: int = 0
    general_non_packed: int = 1
    general_frame_only: int = 1
    max_12bit: int = 0
    max_10bit: int = 0
    max_8bit: int = 0
    max_422chroma: int = 0
    max_420chroma: int = 0
    max_monochrome: int = 0
    inbld: int = 0
    one_picture_only: int = 0
    lower_bit_rate: int = 1
    max_14bit: int = 0


def _validate_profile(c: Content, pdef: HEVCProfileDef):
    """Validate content parameters against a profile definition."""
    if c.bit_depth > pdef.max_depth:
        raise ValueError(
            f"Profile {pdef.idc} ({pdef.name}) supports max {pdef.max_depth}-bit, "
            f"got {c.bit_depth}-bit")
    if c.chroma not in pdef.chroma_set:
        allowed = ", ".join(str(ch) for ch in sorted(pdef.chroma_set, key=str))
        raise ValueError(
            f"Profile {pdef.idc} ({pdef.name}) supports chroma [{allowed}], "
            f"got {c.chroma}")


def _auto_select_profile_idc(c: Content) -> int:
    """
    Auto-detect the tightest HEVC profile from content parameters + flags.

    Decision tree (most specialized first, fallback to general):

      multiview?
        ├─ 4:2:0 ≤8-bit   → 6  (Multiview Main)
        └─ else            → 13 (Multiview Range Extensions)

      scalable?
        ├─ 4:2:0 ≤8-bit   → 7  (Scalable Main)
        ├─ 4:2:0 ≤10-bit  → 8  (Scalable Main 10)
        └─ else            → 12 (Scalable Range Extensions)

      screen_content + intra_only?
        ├─ 4:4:4 or >10-bit → 11 (High Throughput SCC)
        ├─ 4:2:0 >8-bit     → 10 (SCC 10-bit)
        └─ 4:2:0 ≤8-bit     → 9  (SCC)

      screen_content? (not intra)
        ├─ 4:2:0 >8-bit     → 10 (SCC 10-bit)
        ├─ 4:2:0 ≤8-bit     → 9  (SCC)
        └─ else              → 4  (RExt, no non-intra SCC for 4:2:2/4:4:4)

      intra_only? (not SCC)
        ├─ 4:4:4 or >10-bit → 5  (High Throughput)
        └─ else              → (fall through to standard)

      still_image?
        ├─ 4:2:0 ≤8-bit     → 3  (Main Still Picture)
        └─ else              → (fall through to standard)

      (standard — no flags)
        ├─ 4:2:0 ≤8-bit     → 1  (Main)
        ├─ 4:2:0 ≤10-bit    → 2  (Main 10)
        └─ else              → 4  (Range Extensions)
    """
    d = c.bit_depth
    ch = c.chroma
    is_420 = (ch == Chroma.YUV420)

    # ── Multiview (stereo 3D, multi-camera) ──
    if c.multiview:
        if is_420 and d <= 8:
            return 6    # Multiview Main
        return 13       # Multiview Range Extensions

    # ── Scalable (SHVC spatial/SNR/temporal layers) ──
    if c.scalable:
        if is_420 and d <= 8:
            return 7    # Scalable Main
        if is_420 and d <= 10:
            return 8    # Scalable Main 10
        return 12       # Scalable Range Extensions

    # ── Screen content + intra-only → High Throughput SCC ──
    if c.screen_content and c.intra_only:
        if ch == Chroma.YUV444 or d > 10:
            return 11   # High Throughput SCC (4:4:4, 8-16 bit)
        # 4:2:0 ≤10-bit: regular SCC profiles suffice
        if d > 8:
            return 10   # SCC 10-bit
        return 9        # SCC

    # ── Screen content (not intra) ──
    if c.screen_content:
        if is_420 and d > 8 and d <= 10:
            return 10   # SCC 10-bit
        if is_420 and d <= 8:
            return 9    # SCC
        # Non-4:2:0 SCC without intra → no SCC profile fits
        # Fall through to RExt (profile 4)

    # ── Intra-only (not SCC) → High Throughput ──
    if c.intra_only:
        if ch == Chroma.YUV444 or d > 10:
            return 5    # High Throughput (4:4:4, 8-16 bit, intra)
        # 4:2:0 intra ≤10-bit → no special profile, use standard

    # ── Still image ──
    if c.still_image:
        if is_420 and d <= 8:
            return 3    # Main Still Picture

    # ── Standard profiles (no flags) ──
    if is_420 and d <= 8:
        return 1        # Main
    if is_420 and d <= 10:
        return 2        # Main 10
    return 4            # Range Extensions


def _compute_compat_flags(pdef: HEVCProfileDef) -> int:
    """Build 32-bit general_profile_compatibility_flag word."""
    flags = 0
    for bit in pdef.compat_bits:
        flags |= (1 << bit)
    return flags


def _rext_sub_profile_name(d: int, ch: Chroma) -> str:
    """Human-readable RExt sub-profile name."""
    if ch == Chroma.MONO:
        return f"Monochrome{'' if d == 8 else f' {d}'}"
    elif ch == Chroma.YUV420:
        return f"Main {d}"
    elif ch == Chroma.YUV422:
        return f"Main 4:2:2 {d}"
    elif ch == Chroma.YUV444:
        return "Main 4:4:4" if d == 8 else f"Main 4:4:4 {d}"
    return f"RExt {d}-bit {ch}"


def resolve_hevc_profile(c: Content) -> HEVCProfile:
    """
    Select the correct HEVC profile and compute all constraint flags
    deterministically from content parameters.

    Uses --hevc-profile if set (validates content against that profile).
    Otherwise auto-detects from content → profiles 1, 2, or 4.
    """
    d = c.bit_depth
    ch = c.chroma

    # ── Select profile definition ──
    if c.hevc_profile is not None:
        pidc = c.hevc_profile
        if pidc not in HEVC_PROFILE_DEFS:
            raise ValueError(
                f"Unknown HEVC profile: {pidc}. "
                f"Valid: {sorted(HEVC_PROFILE_DEFS.keys())}")
        pdef = HEVC_PROFILE_DEFS[pidc]
        _validate_profile(c, pdef)
    else:
        pidc = _auto_select_profile_idc(c)
        pdef = HEVC_PROFILE_DEFS[pidc]

    # ── Build resolved profile ──
    p = HEVCProfile(
        idc=pidc,
        name=pdef.name,
        compat_flags=_compute_compat_flags(pdef),
    )

    # Profile-specific overrides
    if pidc == 3:
        p.one_picture_only = 1   # Main Still Picture

    # Human-readable sub-profile name for RExt family (4, 12, 13)
    if pidc in (4, 12, 13):
        p.name = _rext_sub_profile_name(d, ch)

    # ── Scan type flags ──
    if c.scan == Scan.INTERLACED:
        p.general_progressive = 0
        p.general_interlaced = 1
        p.general_frame_only = 0
    else:
        p.general_progressive = 1
        p.general_interlaced = 0
        p.general_frame_only = 1

    p.general_non_packed = 1
    p.lower_bit_rate = 1

    # ── Constraint byte depth/chroma flags ──
    if c.constraint_style == ConstraintStyle.FULL:
        # FULL: assert every truthful depth constraint flag
        # Covers the full 8-16 range per ITU-T H.265 Annex A
        if d <= 8:
            p.max_8bit, p.max_10bit, p.max_12bit, p.max_14bit = 1, 1, 1, 1
        elif d <= 10:
            p.max_8bit, p.max_10bit, p.max_12bit, p.max_14bit = 0, 1, 1, 1
        elif d <= 12:
            p.max_8bit, p.max_10bit, p.max_12bit, p.max_14bit = 0, 0, 1, 1
        elif d <= 14:
            p.max_8bit, p.max_10bit, p.max_12bit, p.max_14bit = 0, 0, 0, 1
        else:
            # 15 or 16-bit: no depth constraint can be asserted
            p.max_8bit, p.max_10bit, p.max_12bit, p.max_14bit = 0, 0, 0, 0

        # FULL: assert every truthful chroma constraint flag
        if ch == Chroma.MONO:
            p.max_monochrome, p.max_420chroma, p.max_422chroma = 1, 1, 1
        elif ch == Chroma.YUV420:
            p.max_monochrome, p.max_420chroma, p.max_422chroma = 0, 1, 1
        elif ch == Chroma.YUV422:
            p.max_monochrome, p.max_420chroma, p.max_422chroma = 0, 0, 1
        elif ch == Chroma.YUV444:
            p.max_monochrome, p.max_420chroma, p.max_422chroma = 0, 0, 0
    else:
        # MINIMAL: no depth/chroma constraint assertions
        p.max_8bit, p.max_10bit, p.max_12bit, p.max_14bit = 0, 0, 0, 0
        p.max_monochrome, p.max_420chroma, p.max_422chroma = 0, 0, 0
        p.lower_bit_rate = 0

    return p


# =============================================================================
# HEVC CODEC STRING FORMATTING (ISO/IEC 14496-15 Annex E)
# =============================================================================

PROFILE_SPACE_CHAR = {0: "", 1: "A", 2: "B", 3: "C"}
TIER_CHAR = {0: "L", 1: "H"}


def format_hevc_string(entry: str, profile: HEVCProfile,
                       tier: int, level: HEVCLevel) -> str:
    """
    Build the codec string:
    <entry>.<space><profile_idc>.<compat_hex>.<tier><level_idc>.<constraints>
    """
    # Constraint bytes
    byte0 = ((profile.general_progressive << 7) |
             (profile.general_interlaced  << 6) |
             (profile.general_non_packed  << 5) |
             (profile.general_frame_only  << 4) |
             (profile.max_12bit           << 3) |
             (profile.max_10bit           << 2) |
             (profile.max_8bit            << 1) |
             (profile.max_422chroma       << 0))

    byte1 = ((profile.max_420chroma   << 7) |
             (profile.max_monochrome  << 6) |
             (profile.inbld           << 5) |
             (profile.one_picture_only << 4) |
             (profile.lower_bit_rate  << 3) |
             (profile.max_14bit       << 2))

    cbytes = [byte0, byte1, 0, 0, 0, 0]

    # Encode constraint bytes: dot-separated hex, trailing zeros stripped
    last_nz = -1
    for i in range(5, -1, -1):
        if cbytes[i] != 0:
            last_nz = i
            break

    sp = PROFILE_SPACE_CHAR[profile.profile_space]
    ti = TIER_CHAR[tier]
    base = f"{entry}.{sp}{profile.idc}.{profile.compat_flags:X}.{ti}{level.idc}"

    if last_nz >= 0:
        cstr = ".".join(f"{cbytes[i]:X}" for i in range(last_nz + 1))
        return f"{base}.{cstr}"
    return base


# =============================================================================
# DOLBY VISION LEVEL TABLE

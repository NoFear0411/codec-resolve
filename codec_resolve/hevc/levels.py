"""
HEVC level table and resolution logic.

Source: ITU-T H.265 Table A.6 — General tier and level limits.
"""
import math
from dataclasses import dataclass
from ..models import Content


@dataclass
class HEVCLevel:
    number: float       # e.g. 5.1
    idc: int            # e.g. 153
    max_luma_ps: int
    max_luma_sps: int
    max_br_main: int    # kbps, Main tier
    max_br_high: int    # kbps, High tier (0 = no High tier)

    @property
    def has_high_tier(self) -> bool:
        return self.max_br_high > 0

    @property
    def max_dim(self) -> int:
        """Max dimension per Table A.6 Note 2."""
        return min(int(math.sqrt(self.max_luma_ps * 8)), 16888)


HEVC_LEVELS = [
    HEVCLevel(1.0,  30,    36864,       552960,    128,      0),
    HEVCLevel(2.0,  60,   122880,      3686400,   1500,      0),
    HEVCLevel(2.1,  63,   245760,      7372800,   3000,      0),
    HEVCLevel(3.0,  90,   552960,     16588800,   6000,      0),
    HEVCLevel(3.1,  93,   983040,     33177600,  10000,      0),
    HEVCLevel(4.0, 120,  2228224,     66846720,  12000,  30000),
    HEVCLevel(4.1, 123,  2228224,    133693440,  20000,  50000),
    HEVCLevel(5.0, 150,  8912896,    267386880,  25000, 100000),
    HEVCLevel(5.1, 153,  8912896,    534773760,  40000, 160000),
    HEVCLevel(5.2, 156,  8912896,   1069547520,  60000, 240000),
    HEVCLevel(6.0, 180, 35651584,   1069547520,  60000, 240000),
    HEVCLevel(6.1, 183, 35651584,   2139095040, 120000, 480000),
    HEVCLevel(6.2, 186, 35651584,   4278190080, 240000, 800000),
]


def resolve_hevc_level(c: Content) -> HEVCLevel:
    """Find the minimum HEVC level for this content."""
    max_dim = max(c.width, c.height)
    for lv in HEVC_LEVELS:
        if lv.max_luma_ps < c.luma_ps:
            continue
        if lv.max_luma_sps < c.luma_sps:
            continue
        if lv.max_dim < max_dim:
            continue
        return lv
    raise ValueError(
        f"Content {c.width}×{c.height}@{c.fps:g}fps "
        f"({c.luma_sps:,.0f} samples/sec) exceeds all defined HEVC levels. "
        f"Max supported: 7680×4320@60fps (Level 6.2).")


def resolve_hevc_tier(c: Content, level: HEVCLevel) -> int:
    """
    Determine tier: 0=Main, 1=High.

    - If user explicitly requested a tier, use it (if valid for this level)
    - If bitrate is provided, pick the tier it fits in
    - Default: Main tier (0)
    """
    if not level.has_high_tier:
        return 0  # Levels below 4.0 have no High tier

    if c.tier is not None:
        if c.tier == Tier.HIGH and not level.has_high_tier:
            raise ValueError(f"Level {level.number} does not support High tier")
        return c.tier.value

    if c.bitrate_kbps is not None:
        if c.bitrate_kbps > level.max_br_main:
            if c.bitrate_kbps <= level.max_br_high:
                return 1  # High tier
            else:
                raise ValueError(
                    f"Bitrate {c.bitrate_kbps}kbps exceeds Level {level.number} "
                    f"High tier max ({level.max_br_high}kbps)")
        return 0  # Fits in Main tier

    return 0  # Default: Main tier


# =============================================================================
# HEVC PROFILE DEFINITIONS (ITU-T H.265 Annex A — all 13 profiles)
#
# "8–16 bit" means every integer depth: 8, 9, 10, 11, 12, 13, 14, 15, 16.
#
# IDC  Name                        Depth   Chroma              Compat bits
# ───  ──────────────────────────  ──────  ──────────────────  ───────────
#  1   Main                        8       4:2:0               {1,2}
#  2   Main 10                     8-10    4:2:0               {2}
#  3   Main Still Picture          8       4:2:0               {1,2,3}
#  4   Range Extensions (RExt)     8-16    4:2:0/4:2:2/4:4:4/mono  {4}
#  5   High Throughput             8-16    4:4:4               {5}
#  6   Multiview Main              8       4:2:0               {1,2,6}
#  7   Scalable Main               8       4:2:0               {1,2,7}
#  8   Scalable Main 10            8-10    4:2:0               {2,8}
#  9   Screen Content Coding       8       4:2:0               {1,9}
# 10   Screen Content Coding 10    8-10    4:2:0               {2,10}
# 11   High Throughput SCC         8-16    4:4:4               {5,11}
# 12   Scalable Range Extensions   8-16    4:2:0/4:2:2/4:4:4/mono  {4,12}
# 13   Multiview Range Extensions  8-16    4:2:0/4:2:2/4:4:4/mono  {4,13}
# =============================================================================

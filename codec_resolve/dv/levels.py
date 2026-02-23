"""
Dolby Vision level table and DV↔base-layer level mappings.

Source: ETSI TS 103 572, Dolby ISOBMFF Spec.
"""
import math
from dataclasses import dataclass
from ..models import Content


@dataclass
class DVLevel:
    id: int
    max_width: int
    max_height: int
    max_fps: float
    max_pps: int          # Max pixels per second
    max_br_main: int      # kbps
    max_br_high: int      # kbps (0 = no high tier)


DV_LEVELS = [
    DVLevel(1,  1280,   720,   24,      22118400,    20000,       0),
    DVLevel(2,  1280,   720,   30,      27648000,    20000,       0),
    DVLevel(3,  1920,  1080,   24,      49766400,    25000,       0),
    DVLevel(4,  1920,  1080,   30,      62208000,    30000,       0),
    DVLevel(5,  1920,  1080,   60,     124416000,    40000,       0),
    DVLevel(6,  3840,  2160,   24,     199065600,    50000,  100000),
    DVLevel(7,  3840,  2160,   30,     248832000,    60000,  100000),
    DVLevel(8,  3840,  2160,   48,     398131200,    80000,  160000),
    DVLevel(9,  3840,  2160,   60,     497664000,   100000,  200000),
    DVLevel(10, 3840,  2160,  120,     995328000,   150000,  400000),
    DVLevel(11, 7680,  4320,   24,     796262400,   200000,  400000),
    DVLevel(12, 7680,  4320,   30,     995328000,   250000,  600000),
    DVLevel(13, 7680,  4320,   60,    1990656000,   400000,  800000),
]

DV_LEVEL_LOOKUP = {lv.id: lv for lv in DV_LEVELS}

# DV Level → minimum HEVC Level IDC mapping
# Per Dolby Vision Streams Within the ISOBMFF spec, each DV level
# implies a minimum HEVC decoding capability. The HEVC level must be
# AT LEAST this IDC to decode the DV content.
#
# DV L01-02: 720p     → HEVC L2.0 (60)  — SD/mobile content floor
# DV L03-04: 1080p30  → HEVC L3.0 (90)  — 1080p decode (L4.0 is High Profile)
# DV L05:    1080p60  → HEVC L3.1 (93)  — 1080p high-frame-rate floor
# DV L06:    4K24     → HEVC L4.0 (120) — 4K decode entry
# DV L07:    4K30     → HEVC L4.1 (123) — 4K30 industry floor
# DV L08-09: 4K48-60  → HEVC L5.0 (150) — 4K high-frame-rate
# DV L10:    4K120    → HEVC L5.2 (156) — 4K ultra-high-frame-rate
# DV L11-12: 8K30     → HEVC L6.1 (183) — 8K decode
# DV L13:    8K60     → HEVC L6.2 (186) — 8K high-frame-rate
DV_TO_HEVC_LEVEL_IDC = {
    1:  60,    # 720p24   → L2.0
    2:  60,    # 720p30   → L2.0
    3:  90,    # 1080p24  → L3.0
    4:  90,    # 1080p30  → L3.0
    5:  93,    # 1080p60  → L3.1
    6:  120,   # 4K24     → L4.0
    7:  123,   # 4K30     → L4.1
    8:  150,   # 4K48     → L5.0
    9:  150,   # 4K60     → L5.0
    10: 156,   # 4K120    → L5.2
    11: 183,   # 8K24     → L6.1
    12: 183,   # 8K30     → L6.1
    13: 186,   # 8K60     → L6.2
}

# DV Level → minimum AV1 seq_level_idx mapping
# Derived by matching DV level resolution×fps to the minimum AV1 level
# whose MaxPicSize and MaxDisplayRate cover the same content.
#
# DV L01:    720p24   → AV1 L3.1 (idx 5)   — 1065024 pic covers 1280×720
# DV L02:    720p30   → AV1 L3.1 (idx 5)
# DV L03:    1080p24  → AV1 L4.0 (idx 8)   — 2359296 pic covers 1920×1080
# DV L04:    1080p30  → AV1 L4.0 (idx 8)
# DV L05:    1080p60  → AV1 L4.1 (idx 9)   — display rate needs 4.1
# DV L06:    4K24     → AV1 L5.0 (idx 12)  — 8912896 pic covers 3840×2160
# DV L07:    4K30     → AV1 L5.0 (idx 12)
# DV L08:    4K48     → AV1 L5.1 (idx 13)  — display rate exceeds 5.0
# DV L09:    4K60     → AV1 L5.1 (idx 13)
# DV L10:    4K120    → AV1 L5.2 (idx 14)  — display rate needs 5.2
# DV L11:    8K24     → AV1 L6.0 (idx 16)  — 35651584 pic covers 7680×4320
# DV L12:    8K30     → AV1 L6.0 (idx 16)
# DV L13:    8K60     → AV1 L6.1 (idx 17)  — display rate needs 6.1
DV_TO_AV1_LEVEL_IDX = {
    1:   5,   # 720p24   → L3.1
    2:   5,   # 720p30   → L3.1
    3:   8,   # 1080p24  → L4.0
    4:   8,   # 1080p30  → L4.0
    5:   9,   # 1080p60  → L4.1
    6:  12,   # 4K24     → L5.0
    7:  12,   # 4K30     → L5.0
    8:  13,   # 4K48     → L5.1
    9:  13,   # 4K60     → L5.1
    10: 14,   # 4K120    → L5.2
    11: 16,   # 8K24     → L6.0
    12: 16,   # 8K30     → L6.0
    13: 17,   # 8K60     → L6.1
}


def resolve_dv_level(c: Content) -> DVLevel:
    """Find the minimum DV level for this content."""
    pps = c.luma_sps
    for lv in DV_LEVELS:
        if lv.max_width < c.width:
            continue
        if lv.max_height < c.height:
            continue
        if lv.max_fps < c.fps:
            continue
        if lv.max_pps < pps:
            continue
        return lv
    raise ValueError(
        f"Content {c.width}×{c.height}@{c.fps:g}fps exceeds all DV levels. "
        f"Max supported: 7680×4320@60fps (DV Level 13).")


# =============================================================================
# DV ↔ BASE LAYER COMPATIBILITY
#
# Dolby Vision profiles define a contract between the DV metadata (RPU) and
# the base layer video codec. The base codec varies by profile:
#
#   HEVC:     Profiles 5, 7, 8.x (dvhe/dvh1)
#   AVC:      Profile 9          (dvav/dva1)
#   AV1:      Profile 10         (dav1)
#   MV-HEVC:  Profile 20         (dvh1)
#
# For HLS hybrid strings ("hvc1.2.4.L153.B0, dvh1.08.06"), the HEVC base
# layer must satisfy specific constraints for the DV profile.
#
# Key corrections from Dolby CMS / ETSI TS 103 572:
#   - Profile 5 uses IPTPQc2 (proprietary colorspace) — NOT standard YCbCr.
#     Playing P5 as standard HEVC Main 10 produces green/purple distortion.
#     It is a CLOSED-LOOP system with NO standard fallback.
#   - Profile 7 is DUAL-LAYER (BL+EL+RPU) — 10-bit BL + 2-bit EL → 12-bit.
#     BL alone is valid Main 10 PQ, but the full DV intent requires EL.
#   - Profile 10 is AV1, NOT HEVC. Entry is "dav1", not "dvhe"/"dvh1".
#   - Profile 9 is AVC (H.264), entry is "dvav"/"dva1".
#   - Profile 20 is MV-HEVC (multiview), for stereoscopic / Vision Pro.
# =============================================================================

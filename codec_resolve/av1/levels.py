"""
AV1 level table and tier resolution.

Source: AV1 Bitstream & Decoding Process Specification, Annex A.
Level naming: X = 2 + (seq_level_idx >> 2), Y = seq_level_idx & 3.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
from ..models import Content


@dataclass
class AV1Level:
    seq_level_idx: int           # 0-23, or 31 (unconstrained)
    name: str                    # "2.0", "5.1", etc.
    max_pic_size: int            # max luma samples per frame
    max_h_size: int              # max horizontal luma samples
    max_v_size: int              # max vertical luma samples
    max_display_rate: int        # max luma sample rate (samples/sec)
    max_decode_rate: int         # max decode luma sample rate
    main_mbps: float             # Main tier max bitrate (Mbit/s)
    high_mbps: Optional[float]   # High tier max bitrate (None = no High tier)
    main_cr: float               # Main tier min compression ratio
    high_cr: Optional[float]     # High tier min compression ratio
    max_tiles: int
    max_tile_cols: int


# Annex A Tables A.1 and A.2
# Only levels with defined entries are listed. Gaps (2.2, 2.3, 3.2, 3.3,
# 4.2, 4.3, 7.x) are NOT defined in the spec.

AV1_LEVELS: List[AV1Level] = [
    # idx  name  MaxPicSize  MaxH   MaxV     MaxDisplayRate    MaxDecodeRate       MainMbps HighMbps MainCR HighCR Tiles TileCols
    AV1Level( 0, "2.0",    147456,  2048,  1152,     4423680,      5529600,    1.5, None, 2.0, None,  8, 4),
    AV1Level( 1, "2.1",    278784,  2816,  1584,     8363520,     10454400,    3.0, None, 2.0, None,  8, 4),
    AV1Level( 4, "3.0",    665856,  4352,  2448,    19975680,     24969600,    6.0, None, 2.0, None, 16, 6),
    AV1Level( 5, "3.1",   1065024,  5504,  3096,    31950720,     39938400,   10.0, None, 2.0, None, 16, 6),
    AV1Level( 8, "4.0",   2359296,  6144,  3456,    66846720,     77856768,   12.0, 30.0, 4.0, 4.0, 32, 8),
    AV1Level( 9, "4.1",   2359296,  6144,  3456,   133693440,    155713536,   20.0, 50.0, 4.0, 4.0, 32, 8),
    AV1Level(12, "5.0",   8912896,  8192,  4352,   267386880,    273715200,   30.0, 100.0, 6.0, 4.0, 64, 8),
    AV1Level(13, "5.1",   8912896,  8192,  4352,   534773760,    547430400,   40.0, 160.0, 8.0, 4.0, 64, 8),
    AV1Level(14, "5.2",   8912896,  8192,  4352,  1069547520,   1094860800,   60.0, 240.0, 8.0, 4.0, 64, 8),
    AV1Level(15, "5.3",   8912896,  8192,  4352,  1069547520,   1176502272,   60.0, 240.0, 8.0, 4.0, 64, 8),
    AV1Level(16, "6.0",  35651584, 16384,  8704,  1069547520,   1176502272,   60.0, 240.0, 8.0, 4.0, 128, 16),
    AV1Level(17, "6.1",  35651584, 16384,  8704,  2139095040,   2189721600,  100.0, 480.0, 8.0, 4.0, 128, 16),
    AV1Level(18, "6.2",  35651584, 16384,  8704,  4278190080,   4379443200,  160.0, 800.0, 8.0, 4.0, 128, 16),
    AV1Level(19, "6.3",  35651584, 16384,  8704,  4278190080,   4706009088,  160.0, 800.0, 8.0, 4.0, 128, 16),
]

AV1_LEVEL_LOOKUP: Dict[int, AV1Level] = {lv.seq_level_idx: lv for lv in AV1_LEVELS}


def _level_name_from_idx(idx: int) -> str:
    """Compute level name from seq_level_idx using spec formula."""
    if idx == 31:
        return "Max (unconstrained)"
    x = 2 + (idx >> 2)
    y = idx & 3
    return f"{x}.{y}"


def resolve_av1_level(c: Content) -> AV1Level:
    """Select the minimum AV1 level that covers content resolution + fps."""
    c.validate()
    pic_size = c.width * c.height
    display_rate = pic_size * c.fps

    for lv in AV1_LEVELS:
        if (pic_size <= lv.max_pic_size
                and c.width <= lv.max_h_size
                and c.height <= lv.max_v_size
                and display_rate <= lv.max_display_rate):
            return lv

    raise ValueError(
        f"No AV1 level supports {c.width}×{c.height}@{c.fps}fps "
        f"(pic_size={pic_size}, display_rate={display_rate:.0f}). "
        f"Max defined: Level 6.3 ({AV1_LEVELS[-1].max_h_size}×"
        f"{AV1_LEVELS[-1].max_v_size})")


def resolve_av1_tier(c: Content, level: AV1Level) -> int:
    """Select Main (0) or High (1) tier based on bitrate."""
    if level.high_mbps is None:
        return 0  # levels < 4.0 have no High tier

    if c.tier is not None:
        from ..models import Tier
        if c.tier == Tier.MAIN:
            return 0
        elif c.tier == Tier.HIGH:
            return 1

    # Auto: use High tier only if bitrate exceeds Main cap
    if c.bitrate_kbps and c.bitrate_kbps > level.main_mbps * 1000:
        return 1
    return 0

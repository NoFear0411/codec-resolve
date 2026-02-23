"""
VP9 level table and resolution.

Source: VP9 Bitstream Specification Annex A,
        webmproject.org/vp9/levels/.

Level value in codec string: major × 10 + minor.
No tiers — VP9 has a single max bitrate per level.
No Level 0 in codec strings — ISOBMFF binding defines 10–62 only.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
from ..models import Content


@dataclass
class VP9Level:
    value: int                    # 10, 20, 21, ..., 62
    name: str                     # "1", "2", "2.1", etc.
    max_pic_size: int             # max luma samples per frame
    max_dim: int                  # max(width, height) limit
    max_sample_rate: int          # max luma sample rate (samples/sec)
    max_bitrate_kbps: int         # max bitrate in kbps
    max_cpb_kbps: Optional[int]   # coded picture buffer (None for 5.2+)
    min_cr: int                   # min compression ratio
    max_tiles: int


# VP9 Bitstream Specification Annex A + webmproject.org/vp9/levels/
# 13 defined levels. MaxCPB undefined ("TBD") for levels 5.2+.

VP9_LEVELS: List[VP9Level] = [
    # value  name      MaxPicSize  MaxDim  MaxSampleRate      MaxBR    MaxCPB  MinCR  MaxTiles
    VP9Level( 10, "1",     36_864,    512,        829_440,       200,     400,    2,    1),
    VP9Level( 20, "2",    122_880,    960,      4_608_000,     1_800,   1_500,    2,    1),
    VP9Level( 21, "2.1",  245_760,  1_344,      9_216_000,     3_600,   2_800,    2,    2),
    VP9Level( 30, "3",    552_960,  2_048,     20_736_000,     7_200,   6_000,    2,    4),
    VP9Level( 31, "3.1",  983_040,  2_752,     36_864_000,    12_000,  10_000,    2,    4),
    VP9Level( 40, "4",  2_228_224,  4_160,     83_558_400,    18_000,  16_000,    4,    4),
    VP9Level( 41, "4.1", 2_228_224, 4_160,    160_432_128,    30_000,  18_000,    4,    4),
    VP9Level( 50, "5",  8_912_896,  8_384,    311_951_360,    60_000,  36_000,    6,    8),
    VP9Level( 51, "5.1", 8_912_896, 8_384,    588_251_136,   120_000,  46_000,    8,    8),
    VP9Level( 52, "5.2", 8_912_896, 8_384,  1_176_502_272,   180_000,    None,    8,    8),
    VP9Level( 60, "6", 35_651_584, 16_832,  1_176_502_272,   180_000,    None,    8,   16),
    VP9Level( 61, "6.1", 35_651_584, 16_832, 2_353_004_544,  240_000,    None,    8,   16),
    VP9Level( 62, "6.2", 35_651_584, 16_832, 4_706_009_088,  480_000,    None,    8,   16),
]

VP9_LEVEL_LOOKUP: Dict[int, VP9Level] = {lv.value: lv for lv in VP9_LEVELS}

# Frozen set of valid level values for quick validation in decoder
VP9_VALID_LEVEL_VALUES = frozenset(lv.value for lv in VP9_LEVELS)


def _level_name_from_value(value: int) -> str:
    """Compute level name from codec string value.

    Value encoding: major × 10 + minor.
    Level 1 → 10, Level 2.1 → 21, Level 6.2 → 62.
    """
    major = value // 10
    minor = value % 10
    if minor == 0:
        return str(major)
    return f"{major}.{minor}"


def resolve_vp9_level(c: Content) -> VP9Level:
    """Select the minimum VP9 level that covers content parameters.

    Three constraints must all be satisfied:
      1. width × height ≤ MaxPicSize
      2. max(width, height) ≤ MaxDim
      3. width × height × fps ≤ MaxSampleRate
    """
    c.validate()
    pic_size = c.width * c.height
    sample_rate = pic_size * c.fps
    dim = max(c.width, c.height)

    for lv in VP9_LEVELS:
        if (pic_size <= lv.max_pic_size
                and dim <= lv.max_dim
                and sample_rate <= lv.max_sample_rate):
            return lv

    raise ValueError(
        f"No VP9 level supports {c.width}×{c.height}@{c.fps}fps "
        f"(pic_size={pic_size}, max_dim={dim}, "
        f"sample_rate={sample_rate:.0f}). "
        f"Max defined: Level 6.2 "
        f"(max_dim={VP9_LEVELS[-1].max_dim})")

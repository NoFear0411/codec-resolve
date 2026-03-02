"""
AVC/H.264 level table and resolution logic.

Source: ITU-T H.264 §A.3, Table A-1.
        Levels 6.0–6.2 from later H.264 amendments.

AVC levels are macroblock-based (16×16 pixels). MaxFS is in MB count.
Resolution lookup converts pixel dimensions to MB grid: ceil(w/16) × ceil(h/16).
"""
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from ..models import Content


@dataclass
class AVCLevel:
    level_idc: int              # Integer in codec string (hex)
    name: str                   # Display: "1", "1.1", "3.1", etc.
    max_mbps: int               # Max macroblock processing rate (MBs/sec)
    max_fs: int                 # Max frame size (MBs)
    max_br_kbps: int            # Max bitrate (kbps, Baseline/Main/Extended)
    example: str                # Typical resolution


# Level 1b: level_idc=11 with constraint_set3_flag=1 (or alternate level_idc=9)
# Handled specially in the decoder. In this table we represent it as idc=9
# to keep the lookup unambiguous. The decoder maps both representations.

AVC_LEVELS: List[AVCLevel] = [
    AVCLevel(10,  "1",     1_485,         99,        64,   "176×144@15"),
    AVCLevel(9,   "1b",    1_485,        396,       128,   "176×144@15"),
    AVCLevel(11,  "1.1",   3_000,        396,       192,   "352×288@7.5"),
    AVCLevel(12,  "1.2",   6_000,        396,       384,   "352×288@15"),
    AVCLevel(13,  "1.3",  11_880,        396,       768,   "352×288@30"),
    AVCLevel(20,  "2",    11_880,        396,      2_000,  "352×288@30"),
    AVCLevel(21,  "2.1",  19_800,        792,      4_000,  "352×480@30"),
    AVCLevel(22,  "2.2",  20_250,      1_620,      4_000,  "720×480@15"),
    AVCLevel(30,  "3",    40_500,      1_620,     10_000,  "720×480@30"),
    AVCLevel(31,  "3.1", 108_000,      3_600,     14_000,  "1280×720@30"),
    AVCLevel(32,  "3.2", 216_000,      5_120,     20_000,  "1280×1024@42"),
    AVCLevel(40,  "4",   245_760,      8_192,     20_000,  "1920×1080@30"),
    AVCLevel(41,  "4.1", 245_760,      8_192,     50_000,  "1920×1080@30"),
    AVCLevel(42,  "4.2", 522_240,      8_704,     50_000,  "1920×1080@64"),
    AVCLevel(50,  "5",   589_824,     22_080,    135_000,  "3840×2160@30"),
    AVCLevel(51,  "5.1", 983_040,     36_864,    240_000,  "4096×2160@30"),
    AVCLevel(52,  "5.2", 2_073_600,   36_864,    240_000,  "4096×2160@60"),
    AVCLevel(60,  "6",   5_242_880,  139_264,    240_000,  "8192×4352@30"),
    AVCLevel(61,  "6.1", 10_485_760, 139_264,    480_000,  "8192×4352@60"),
    AVCLevel(62,  "6.2", 20_971_520, 139_264,    800_000,  "8192×4352@120"),
]

AVC_LEVEL_LOOKUP: Dict[int, AVCLevel] = {
    lv.level_idc: lv for lv in AVC_LEVELS
}

AVC_VALID_LEVEL_IDCS: Set[int] = set(AVC_LEVEL_LOOKUP.keys())


# ── Bitrate multipliers (ITU-T H.264 Table A-2, Note 2) ──────────────
# MaxBR in the level table is for Baseline/Main/Extended.
# Higher profiles get a multiplier on top.

BITRATE_PROFILE_MULTIPLIER: Dict[int, float] = {
    66:  1.0,     # Baseline
    77:  1.0,     # Main
    88:  1.0,     # Extended
    100: 1.25,    # High
    110: 3.0,     # High 10
    122: 4.0,     # High 4:2:2
    244: 4.0,     # High 4:4:4 Predictive
    44:  4.0,     # CAVLC 4:4:4 Intra
}


# ── Level resolution (forward) ───────────────────────────────────────

def _mb_dims(width: int, height: int):
    """Convert pixel dimensions to macroblock dimensions (ceil)."""
    return math.ceil(width / 16), math.ceil(height / 16)


def resolve_avc_level(c: Content) -> AVCLevel:
    """Select the minimum AVC level that covers content parameters.

    AVC levels constrain by macroblock count and rate, not raw pixels:
      MaxFS  = max frame size in macroblocks (16×16)
      MaxMBPS = max macroblock processing rate (MBs/sec)
    """
    c.validate()
    mb_w, mb_h = _mb_dims(c.width, c.height)
    frame_mbs = mb_w * mb_h
    mb_rate = frame_mbs * c.fps

    for lv in AVC_LEVELS:
        if frame_mbs <= lv.max_fs and mb_rate <= lv.max_mbps:
            return lv

    top = AVC_LEVELS[-1]
    raise ValueError(
        f"No AVC level supports {c.width}×{c.height}@{c.fps:g}fps "
        f"(frame={frame_mbs} MBs, rate={mb_rate:,.0f} MBs/s). "
        f"Max defined: Level {top.name} "
        f"(MaxFS={top.max_fs:,}, MaxMBPS={top.max_mbps:,})")

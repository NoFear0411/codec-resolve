"""
AVC/H.264 profile definitions, constraint flag parsing, and selection logic.

Source: ITU-T H.264 §A.2 (profiles), §7.4.2.1 (constraint flags).
"""
from dataclasses import dataclass
from typing import Dict, Optional, Set
from ..models import Content, Chroma


# ── Profile definitions ─────────────────────────────────────────────

@dataclass
class AVCProfileDef:
    profile_idc: int
    name: str
    max_bit_depth: int
    allowed_chroma: Set[Chroma]
    bitrate_multiplier: float     # MaxBR multiplier vs Baseline/Main (Table A-2)
    note: str


_420 = {Chroma.YUV420}
_420_422 = {Chroma.YUV420, Chroma.YUV422}
_ALL = {Chroma.YUV420, Chroma.YUV422, Chroma.YUV444}

AVC_PROFILE_DEFS: Dict[int, AVCProfileDef] = {
    66: AVCProfileDef(
        profile_idc=66, name="Baseline",
        max_bit_depth=8, allowed_chroma=_420,
        bitrate_multiplier=1.0,
        note="CAVLC only, no B-frames. Legacy consumer (cameras, old devices)"),
    77: AVCProfileDef(
        profile_idc=77, name="Main",
        max_bit_depth=8, allowed_chroma=_420,
        bitrate_multiplier=1.0,
        note="CABAC, B-frames, weighted prediction. Broadcast standard"),
    88: AVCProfileDef(
        profile_idc=88, name="Extended",
        max_bit_depth=8, allowed_chroma=_420,
        bitrate_multiplier=1.0,
        note="Data partitioning, SP/SI slices. Rare in practice"),
    100: AVCProfileDef(
        profile_idc=100, name="High",
        max_bit_depth=8, allowed_chroma=_420,
        bitrate_multiplier=1.25,
        note="8x8 transform, custom quant matrices. Consumer standard (Blu-ray, Netflix)"),
    110: AVCProfileDef(
        profile_idc=110, name="High 10",
        max_bit_depth=10, allowed_chroma=_420,
        bitrate_multiplier=3.0,
        note="10-bit sample depth. Professional/broadcast"),
    122: AVCProfileDef(
        profile_idc=122, name="High 4:2:2",
        max_bit_depth=10, allowed_chroma=_420_422,
        bitrate_multiplier=4.0,
        note="4:2:2 chroma. Broadcast interlaced, professional"),
    244: AVCProfileDef(
        profile_idc=244, name="High 4:4:4 Predictive",
        max_bit_depth=14, allowed_chroma=_ALL,
        bitrate_multiplier=4.0,
        note="Lossless coding, separate color planes. Studio mastering"),
    44: AVCProfileDef(
        profile_idc=44, name="CAVLC 4:4:4 Intra",
        max_bit_depth=14, allowed_chroma=_ALL,
        bitrate_multiplier=4.0,
        note="Intra-only CAVLC. Lossless capture"),
}

AVC_PROFILE_NAMES: Dict[int, str] = {
    p.profile_idc: p.name for p in AVC_PROFILE_DEFS.values()
}

AVC_VALID_PROFILE_IDCS: Set[int] = set(AVC_PROFILE_DEFS.keys())


# ── Constraint flag parsing ──────────────────────────────────────────

# ITU-T H.264 §7.4.2.1: constraint_set flags in SPS
CONSTRAINT_FLAG_NAMES = [
    "set0",  # bit 7: Baseline-compatible
    "set1",  # bit 6: Main-compatible
    "set2",  # bit 5: Extended-compatible
    "set3",  # bit 4: level 1b / Intra-only (High profiles)
    "set4",  # bit 3: constrained features
    "set5",  # bit 2: frame-only MB-adaptive
]


def parse_constraint_flags(byte_val: int) -> Dict[str, bool]:
    """Parse constraint_set flags byte into named booleans.

    Bits 7-2 are the 6 constraint_set flags.
    Bits 1-0 are reserved_zero_2bits.
    """
    return {
        name: bool((byte_val >> (7 - i)) & 1)
        for i, name in enumerate(CONSTRAINT_FLAG_NAMES)
    }


def get_reserved_bits(byte_val: int) -> int:
    """Extract the reserved_zero_2bits (bits 1-0)."""
    return byte_val & 0x03


# ── Derived constrained profiles ─────────────────────────────────────

# Derived profiles are signaled by constraint flag combinations on top of
# a base profile_idc. These represent decoder-negotiated subsets.

def derive_constrained_profile(profile_idc: int,
                               flags: Dict[str, bool]) -> Optional[str]:
    """Derive a constrained profile name from profile_idc + constraint flags.

    Returns refined name if a constrained variant is detected, else None.
    """
    if profile_idc == 66 and flags.get("set1"):
        return "Constrained Baseline"

    if profile_idc == 100:
        c4 = flags.get("set4", False)
        c5 = flags.get("set5", False)
        if c4 and c5:
            return "Progressive High"
        if c4:
            return "Constrained High"

    return None


# ── Profile selection (forward resolve) ───────────────────────────────

def resolve_avc_profile(c: Content) -> int:
    """Select the minimum AVC profile for the content.

    AVC profile selection is simpler than HEVC (8 vs 13 profiles):
      8-bit + 4:2:0  → High (100)  — consumer standard
      10-bit + 4:2:0 → High 10 (110)
      ≤10-bit + 4:2:2 → High 4:2:2 (122)
      ≤14-bit + 4:4:4 → High 4:4:4 Predictive (244)
    """
    if c.chroma == Chroma.YUV444:
        if c.bit_depth > 14:
            raise ValueError(f"AVC max bit depth is 14, got {c.bit_depth}")
        return 244
    if c.chroma == Chroma.YUV422:
        if c.bit_depth > 10:
            raise ValueError(
                f"AVC High 4:2:2 supports up to 10-bit, got {c.bit_depth}")
        return 122
    if c.chroma == Chroma.MONO:
        # Monochrome is subset of High (4:2:0 with zero chroma)
        if c.bit_depth > 10:
            return 244
        if c.bit_depth > 8:
            return 110
        return 100
    # 4:2:0
    if c.bit_depth > 10:
        raise ValueError(
            f"AVC 4:2:0 supports up to 10-bit, got {c.bit_depth}")
    if c.bit_depth > 8:
        return 110
    return 100


# ── Codec string formatting ──────────────────────────────────────────

def default_constraint_byte(profile_idc: int) -> int:
    """Compute default constraint flags byte for a profile.

    Sets the self-compatibility bit and any implied compatibility bits.
    Reserved bits 1-0 are always 0.
    """
    flags = 0x00

    if profile_idc == 66:
        flags |= 0x80  # set0 (Baseline self-compat)
    elif profile_idc == 77:
        flags |= 0x40  # set1 (Main self-compat)
    elif profile_idc == 88:
        flags |= 0x20  # set2 (Extended self-compat)
    elif profile_idc == 100:
        # High has no mandatory constraint bits
        pass
    elif profile_idc == 110:
        pass
    elif profile_idc == 122:
        pass
    elif profile_idc == 244:
        pass
    elif profile_idc == 44:
        flags |= 0x10  # set3 (Intra-only)

    return flags


def format_avc_string(entry: str, profile_idc: int,
                      constraint_byte: int, level_idc: int) -> str:
    """Format a complete AVC codec string.

    Format: avc1.PPCCLL (6 uppercase hex chars after dot)
    """
    return f"{entry}.{profile_idc:02X}{constraint_byte:02X}{level_idc:02X}"

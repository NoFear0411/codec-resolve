"""
Shared data models for codec_resolve.

Enumerations, Content descriptor, and ResolvedCodec output.
"""
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class Chroma(Enum):
    MONO   = 0
    YUV420 = 1
    YUV422 = 2
    YUV444 = 3

    def __str__(self):
        return {0: "Mono", 1: "4:2:0", 2: "4:2:2", 3: "4:4:4"}[self.value]

    @classmethod
    def parse(cls, s):
        m = {"mono": cls.MONO, "monochrome": cls.MONO, "0": cls.MONO,
             "420": cls.YUV420, "4:2:0": cls.YUV420,
             "422": cls.YUV422, "4:2:2": cls.YUV422,
             "444": cls.YUV444, "4:4:4": cls.YUV444}
        r = m.get(s.lower().strip())
        if r is None:
            raise ValueError(f"Unknown chroma: '{s}'. Use: mono/420/422/444")
        return r


class Transfer(Enum):
    SDR = "sdr"
    PQ  = "pq"
    HLG = "hlg"

    @classmethod
    def parse(cls, s):
        m = {"sdr": cls.SDR, "bt709": cls.SDR, "gamma": cls.SDR,
             "pq": cls.PQ, "st2084": cls.PQ, "hdr10": cls.PQ,
             "hlg": cls.HLG, "arib": cls.HLG, "bbc": cls.HLG}
        r = m.get(s.lower().replace("-", "").replace("_", "").replace(" ", ""))
        if r is None:
            raise ValueError(f"Unknown transfer: '{s}'. Use: sdr/pq/hlg")
        return r


class Gamut(Enum):
    BT709  = "bt709"
    BT2020 = "bt2020"
    P3     = "p3"

    @classmethod
    def parse(cls, s):
        m = {"bt709": cls.BT709, "rec709": cls.BT709, "709": cls.BT709,
             "srgb": cls.BT709,
             "bt2020": cls.BT2020, "rec2020": cls.BT2020, "2020": cls.BT2020,
             "bt2100": cls.BT2020, "rec2100": cls.BT2020,
             "p3": cls.P3, "dcip3": cls.P3, "displayp3": cls.P3, "dci": cls.P3}
        r = m.get(s.lower().replace("-", "").replace("_", "").replace(" ", ""))
        if r is None:
            raise ValueError(f"Unknown gamut: '{s}'. Use: bt709/bt2020/p3")
        return r


class Scan(Enum):
    PROGRESSIVE = "progressive"
    INTERLACED  = "interlaced"


class Tier(Enum):
    MAIN = 0
    HIGH = 1


class ConstraintStyle(Enum):
    """
    Controls how HEVC general_constraint_indicator bytes are populated.

    MINIMAL:
      Only source characteristic flags (progressive, interlaced, non_packed,
      frame_only). All depth/chroma/bitrate constraint bits left at 0.
      This is what x265, FFmpeg, and most real-world encoders produce.
      Example: hvc1.2.4.L150.B0

    FULL:
      Every truthful constraint flag is asserted. If the content is 10-bit,
      max_12bit=1 and max_10bit=1 are set. If 4:2:0, max_422chroma=1 and
      max_420chroma=1 are set. lower_bit_rate=1 is asserted.
      This is maximally informative per ITU-T H.265 Annex A.
      Example: hvc1.2.4.L150.BD.88

    Both are valid per spec — the constraint flags are OPTIONAL assertions.
    0 = "no constraint claimed" (permissive), 1 = "I assert this limit holds"
    (restrictive/informative). Decoders must support both.
    """
    MINIMAL = "minimal"
    FULL    = "full"


# =============================================================================


@dataclass
class Content:
    """Complete description of the media content."""
    width: int
    height: int
    fps: float
    bit_depth: int             # 8-16 (integer, all values valid for RExt profiles)
    chroma: Chroma
    transfer: Transfer
    gamut: Gamut
    bitrate_kbps: Optional[int] = None   # For tier selection
    scan: Scan = Scan.PROGRESSIVE
    tier: Optional[Tier] = None          # None = auto-select

    # DV-specific overrides
    dv_profile: Optional[int] = None     # Force specific DV profile (5/7/8/9/10/20)
    dv_bl_compat_id: Optional[int] = None  # Force BL compat ID for Profile 8

    # HEVC overrides
    hevc_profile: Optional[int] = None   # Force specific HEVC profile (1-13)
    constraint_style: ConstraintStyle = ConstraintStyle.MINIMAL

    # Encoding characteristics (drive auto-detection of profiles 3-13)
    still_image: bool = False            # Single frame (→ Profile 3)
    intra_only: bool = False             # All-intra, no inter-prediction (→ 5, 11)
    screen_content: bool = False         # IBC + palette mode (→ 9, 10, 11)
    scalable: bool = False               # SHVC multi-layer (→ 7, 8, 12)
    multiview: bool = False              # Stereo 3D / multi-camera (→ 6, 13)

    def validate(self):
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Invalid resolution: {self.width}×{self.height}")
        if self.fps <= 0:
            raise ValueError(f"Invalid framerate: {self.fps}")
        if self.bit_depth < 8 or self.bit_depth > 16:
            raise ValueError(f"Bit depth must be 8-16, got {self.bit_depth}")

        # HDR transfer functions require ≥10-bit
        if self.transfer in (Transfer.PQ, Transfer.HLG) and self.bit_depth < 10:
            raise ValueError(
                f"{self.transfer.value.upper()} requires ≥10-bit, "
                f"got {self.bit_depth}-bit")

        # Wide gamut typically paired with HDR (warning, not error)
        if self.gamut == Gamut.BT2020 and self.transfer == Transfer.SDR:
            print(f"  ⚠ BT.2020 gamut with SDR transfer is unusual "
                  f"(valid but uncommon)", file=sys.stderr)

        # still_image implies single frame
        if self.still_image and self.fps > 1:
            print(f"  ⚠ --still with fps={self.fps:g} — still image profiles "
                  f"are single-frame (fps ignored for level selection)",
                  file=sys.stderr)

    @property
    def luma_ps(self) -> int:
        return self.width * self.height

    @property
    def luma_sps(self) -> float:
        return self.width * self.height * self.fps

    def describe(self) -> str:
        parts = [f"{self.width}×{self.height}@{self.fps:g}fps",
                 f"{self.bit_depth}-bit", str(self.chroma),
                 self.transfer.value.upper(), self.gamut.value.upper()]
        if self.dv_bl_compat_id is not None:
            compat_labels = {0: "none", 1: "HDR10", 2: "SDR", 4: "HLG"}
            parts.append(f"compat={compat_labels.get(self.dv_bl_compat_id, self.dv_bl_compat_id)}")
        if self.bitrate_kbps:
            parts.append(f"{self.bitrate_kbps}kbps")
        if self.scan == Scan.INTERLACED:
            parts.append("interlaced")
        flags = []
        if self.still_image:    flags.append("still")
        if self.intra_only:     flags.append("intra")
        if self.screen_content: flags.append("scc")
        if self.scalable:       flags.append("scalable")
        if self.multiview:      flags.append("multiview")
        if flags:
            parts.append("[" + "+".join(flags) + "]")
        return " / ".join(parts)


# =============================================================================


@dataclass
class ResolvedCodec:
    """Complete resolved codec string with explanatory metadata."""
    codec_string: str
    entry: str
    family: str                # "hevc", "dv", or "av1"
    profile_name: str
    level_name: str
    tier_name: str = ""
    notes: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# ITU-T H.273 Color Parameter Tables
# Shared across AV1 (explicit in codec string) and HEVC (VUI/SEI).
# Source: ITU-T H.273 Tables 2, 3, 4.
# ═══════════════════════════════════════════════════════════════════════

COLOR_PRIMARIES = {
    0: "Identity",
    1: "BT.709",
    2: "Unspecified",
    4: "BT.470M (System M)",
    5: "BT.470BG (System B/G)",
    6: "BT.601 (SMPTE 170M)",
    7: "SMPTE 240M",
    8: "Generic Film",
    9: "BT.2020 / BT.2100",
    10: "SMPTE ST 428 (XYZ)",
    11: "SMPTE RP 431 (P3-DCI)",
    12: "SMPTE EG 432 (P3-D65 / Display P3)",
    22: "EBU Tech 3213-E",
}

TRANSFER_CHARACTERISTICS = {
    0: "Reserved",
    1: "BT.709",
    2: "Unspecified",
    4: "BT.470M (Gamma 2.2)",
    5: "BT.470BG (Gamma 2.8)",
    6: "BT.601 (SMPTE 170M)",
    7: "SMPTE 240M",
    8: "Linear",
    9: "Log 100:1",
    10: "Log 316:1",
    11: "IEC 61966-2-4",
    12: "BT.1361 Extended",
    13: "sRGB / sYCC",
    14: "BT.2020 10-bit",
    15: "BT.2020 12-bit",
    16: "PQ (SMPTE ST 2084)",
    17: "SMPTE ST 428",
    18: "HLG (ARIB STD-B67)",
}

MATRIX_COEFFICIENTS = {
    0: "Identity (GBR / ICtCp)",
    1: "BT.709",
    2: "Unspecified",
    4: "FCC 73.682",
    5: "BT.470BG / BT.601",
    6: "BT.601 (SMPTE 170M)",
    7: "SMPTE 240M",
    8: "YCgCo",
    9: "BT.2020 NCL",
    10: "BT.2020 CL",
    11: "SMPTE ST 2085",
    12: "Chromat NCL",
    13: "Chromat CL",
    14: "ICtCp",
}

# Maps from our Transfer/Gamut enums to H.273 integer codes
# Used by AV1 forward resolver (Content → codec string)

TRANSFER_TO_TC = {
    Transfer.SDR: 1,    # BT.709
    Transfer.PQ:  16,   # SMPTE ST 2084
    Transfer.HLG: 18,   # ARIB STD-B67
}

GAMUT_TO_CP = {
    Gamut.BT709:  1,    # BT.709
    Gamut.BT2020: 9,    # BT.2020/BT.2100
    Gamut.P3:     12,   # SMPTE EG 432 (Display P3)
}

# Default matrix coefficients per gamut
GAMUT_TO_MC = {
    Gamut.BT709:  1,    # BT.709
    Gamut.BT2020: 9,    # BT.2020 NCL
    Gamut.P3:     6,    # BT.601 (common for P3 in ISOBMFF)
}

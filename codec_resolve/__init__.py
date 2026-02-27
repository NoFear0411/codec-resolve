"""
HEVC + AV1 + VP9 + VP8 + Dolby Vision Codec String Resolver & Validator
========================================================================
143 tests · zero dependencies · AGPL-3.0

Bidirectional: resolve ↔ decode ↔ validate ↔ hybrid.

Public API:
    resolve()              Content → codec string(s)
    decode_codec_string()  codec string → parsed dict (HEVC, AV1, VP9, VP8, or DV)
    decode_hybrid_string() "hevc/av01, dv" → parsed + cross-validated dict
    decode_hevc()          HEVC string → parsed dict
    decode_av1()           AV1 string → parsed dict
    decode_vp9()           VP9 string → parsed dict
    decode_vp8()           VP8 string → parsed dict
    decode_dv()            DV string → parsed dict
    validate_hybrid()      HEVC dict + DV dict → validation result
    validate_av1_hybrid()  AV1 dict + DV dict → validation result
"""

from .models import (
    Content, Chroma, Transfer, Gamut, Scan, Tier,
    ConstraintStyle, ResolvedCodec,
)
from .resolve import resolve
from .hybrid import (
    decode_codec_string, decode_hybrid_string,
    validate_hybrid, validate_av1_hybrid,
)
from .hevc.decode import decode_hevc
from .av1.decode import decode_av1
from .vp9.decode import decode_vp9
from .vp8.decode import decode_vp8
from .dv.decode import decode_dv

__all__ = [
    "Content", "Chroma", "Transfer", "Gamut", "Scan", "Tier",
    "ConstraintStyle", "ResolvedCodec",
    "resolve",
    "decode_codec_string", "decode_hybrid_string",
    "validate_hybrid", "validate_av1_hybrid",
    "decode_hevc", "decode_av1", "decode_vp9", "decode_vp8", "decode_dv",
]

"""
VP9 codec string decoder with semantic validation.

Decodes vp09 strings into profile, level, bit depth, chroma subsampling,
and color parameters with validation checks.

Source: VP Codec ISO Media File Format Binding §5 (Codecs Parameter String),
        VP9 Bitstream Specification §7.2, Annex A.
"""
from typing import Dict, List
from .profiles import (
    VP9_PROFILE_DEFS, VP9_PROFILE_NAMES,
    CHROMA_FROM_CC, CHROMA_SAMPLE_POSITION_NAMES,
    VALID_CC_FOR_PROFILE,
)
from .levels import VP9_LEVEL_LOOKUP, VP9_VALID_LEVEL_VALUES
from ..models import (
    COLOR_PRIMARIES, TRANSFER_CHARACTERISTICS, MATRIX_COEFFICIENTS,
)
from ..hls import strip_hls_brands


# ── Defaults for optional fields (per VP9-ISOBMFF §5) ───────────
# "If not specified then the values listed in the table below are assumed."
_OPTIONAL_DEFAULTS = {
    "chroma_subsampling": 0,       # 4:2:0 (vertical / left)
    "color_primaries": 1,          # BT.709
    "transfer_characteristics": 1,  # BT.709
    "matrix_coefficients": 1,       # BT.709
    "video_full_range_flag": 0,     # Limited range (studio swing)
}


def decode_vp9(codec_string: str) -> dict:
    """
    Decode a VP9 codec string into a structured dict.

    Accepts:
        "vp09.00.31.08"                            (short: 4 fields)
        "vp09.02.10.10.01.09.16.09.01"             (full: 9 fields)

    Field count must be exactly 4 (short) or 9 (full).
    All fields after the entry point are 2-digit zero-padded integers.
    """
    findings = []
    result = {
        "family": "vp9",
        "findings": findings,
    }

    s = codec_string.strip()

    # ── Step 1: Strip HLS brand suffix (defensive) ────────────────
    # VP9 is not used in HLS, but handle gracefully if someone appends a brand.
    s, hls_brands, unknown_brands = strip_hls_brands(s)
    for ub in unknown_brands:
        findings.append({
            "severity": "warning",
            "code": "VP9_BRAND_UNKNOWN",
            "message": f"Unknown HLS brand '/{ub}' — "
                       f"VP9 does not use HLS brands",
        })
    if hls_brands:
        result["hls_brands"] = hls_brands
        findings.append({
            "severity": "warning",
            "code": "VP9_HLS_UNSUPPORTED",
            "message": "VP9 codec strings do not use HLS "
                       "SUPPLEMENTAL-CODECS brands",
        })
    result["codec_string_full"] = codec_string.strip()

    # ── Step 2: Split and validate entry ──────────────────────────
    parts = s.split(".")
    entry = parts[0]

    if entry != "vp09":
        result["codec_string"] = s
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "VP9_ENTRY_UNKNOWN",
            "message": f"Expected entry 'vp09', got '{entry}'",
        })
        return result

    result["entry"] = "vp09"
    result["entry_meaning"] = "VP9 codec configuration"
    result["codec_string"] = s

    # ── Step 3: Validate field count ──────────────────────────────
    # vp09.PP.LL.DD = 4 fields, vp09.PP.LL.DD.CC.cp.tc.mc.FF = 9 fields
    field_count = len(parts)
    if field_count not in (4, 9):
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "VP9_FIELD_COUNT",
            "message": f"Must have exactly 4 fields (short form) or "
                       f"9 fields (full form), got {field_count}. "
                       f"Partial optional fields are invalid",
        })
        return result

    # ── Step 4: Validate field format (all 2-digit after entry) ───
    for i, part in enumerate(parts[1:], start=1):
        if len(part) != 2 or not part.isdigit():
            result["verdict"] = "INVALID"
            findings.append({
                "severity": "error",
                "code": "VP9_FIELD_FORMAT",
                "message": f"Field {i} ('{part}') must be a 2-digit "
                           f"zero-padded integer",
            })
            return result

    # ── Step 5: Parse mandatory fields ────────────────────────────
    profile = int(parts[1])
    level_value = int(parts[2])
    bit_depth = int(parts[3])

    result["profile"] = profile
    result["profile_idc"] = profile        # standard contract alias
    result["level_value"] = level_value
    result["level_idc"] = level_value      # standard contract alias
    result["bit_depth"] = bit_depth

    # Profile lookup
    if profile not in VP9_PROFILE_DEFS:
        findings.append({
            "severity": "error",
            "code": "VP9_PROFILE_UNKNOWN",
            "message": f"Profile {profile} not in {{0, 1, 2, 3}}",
        })
        result["profile_name"] = f"Unknown ({profile})"
    else:
        pdef = VP9_PROFILE_DEFS[profile]
        result["profile_name"] = pdef.name

    # Level lookup
    level_obj = VP9_LEVEL_LOOKUP.get(level_value)
    if level_value not in VP9_VALID_LEVEL_VALUES:
        findings.append({
            "severity": "error",
            "code": "VP9_LEVEL_UNKNOWN",
            "message": f"Level value {level_value} not in defined levels "
                       f"{sorted(VP9_VALID_LEVEL_VALUES)}",
        })
        result["level_name"] = f"Unknown ({level_value})"
    else:
        result["level_name"] = level_obj.name

    # Standard contract: max_resolution and max_fps from level
    if level_obj:
        result["max_resolution"] = f"{level_obj.max_dim}x{level_obj.max_dim}"
        result["max_fps"] = level_obj.max_sample_rate / level_obj.max_pic_size
    else:
        result["max_resolution"] = None
        result["max_fps"] = None

    # ── Step 6: Parse optional fields or apply defaults ───────────
    has_optional = field_count == 9
    result["has_optional_fields"] = has_optional

    if has_optional:
        chroma_subsampling = int(parts[4])
        color_primaries = int(parts[5])
        transfer_characteristics = int(parts[6])
        matrix_coefficients = int(parts[7])
        video_full_range_flag = int(parts[8])
    else:
        chroma_subsampling = _OPTIONAL_DEFAULTS["chroma_subsampling"]
        color_primaries = _OPTIONAL_DEFAULTS["color_primaries"]
        transfer_characteristics = _OPTIONAL_DEFAULTS["transfer_characteristics"]
        matrix_coefficients = _OPTIONAL_DEFAULTS["matrix_coefficients"]
        video_full_range_flag = _OPTIONAL_DEFAULTS["video_full_range_flag"]
        findings.append({
            "severity": "info",
            "code": "VP9_SHORT_FORM",
            "message": "Short form — using defaults: 4:2:0 (vertical), "
                       "BT.709 primaries/transfer/matrix, limited range",
        })

    result["chroma_subsampling"] = chroma_subsampling
    result["color_primaries"] = color_primaries
    result["transfer_characteristics"] = transfer_characteristics
    result["matrix_coefficients"] = matrix_coefficients
    result["video_full_range_flag"] = video_full_range_flag

    # Resolve chroma enum from CC value
    chroma = CHROMA_FROM_CC.get(chroma_subsampling)
    if chroma is not None:
        result["chroma"] = chroma
        result["chroma_name"] = str(chroma)
    else:
        result["chroma"] = None
        result["chroma_name"] = f"Unknown CC ({chroma_subsampling})"
        findings.append({
            "severity": "error",
            "code": "VP9_CHROMA_UNKNOWN",
            "message": f"Chroma subsampling value {chroma_subsampling} "
                       f"not in {{0, 1, 2, 3}}",
        })

    # Chroma sample position (only meaningful for CC 00/01 = 4:2:0)
    if chroma_subsampling in (0, 1):
        result["chroma_sample_position"] = chroma_subsampling
        result["chroma_sample_position_name"] = (
            CHROMA_SAMPLE_POSITION_NAMES.get(chroma_subsampling, "Unknown"))

    # Resolve H.273 display names
    result["color_primaries_name"] = COLOR_PRIMARIES.get(
        color_primaries, f"Unknown ({color_primaries})")
    result["transfer_characteristics_name"] = TRANSFER_CHARACTERISTICS.get(
        transfer_characteristics, f"Unknown ({transfer_characteristics})")
    result["matrix_coefficients_name"] = MATRIX_COEFFICIENTS.get(
        matrix_coefficients, f"Unknown ({matrix_coefficients})")
    result["video_range_name"] = (
        "Full (PC)" if video_full_range_flag else "Limited (studio swing)")

    # ── Step 7: Semantic validation ───────────────────────────────
    _validate_vp9(result, findings, level_obj)

    # ── Step 8: Bitrate cap info ──────────────────────────────────
    if level_obj:
        result["max_bitrate_kbps"] = level_obj.max_bitrate_kbps
        mbps = level_obj.max_bitrate_kbps / 1000
        findings.append({
            "severity": "info",
            "code": "VP9_BITRATE_CAP",
            "message": f"Max bitrate for Level {level_obj.name}: "
                       f"{mbps:g} Mbps ({level_obj.max_bitrate_kbps} kbps)",
        })

    # ── Verdict ───────────────────────────────────────────────────
    has_errors = any(f["severity"] == "error" for f in findings)
    result["verdict"] = "INVALID" if has_errors else "VALID"

    return result


def _validate_vp9(result: dict, findings: list, level_obj) -> None:
    """Run semantic validation checks on parsed VP9 fields."""
    profile = result.get("profile")
    bit_depth = result.get("bit_depth")
    chroma_subsampling = result.get("chroma_subsampling")

    pdef = VP9_PROFILE_DEFS.get(profile) if profile is not None else None

    # CHECK: Bit depth valid for profile
    if pdef and bit_depth is not None:
        if bit_depth not in pdef.bit_depths:
            findings.append({
                "severity": "error",
                "code": "VP9_DEPTH_INVALID",
                "message": f"{pdef.name} requires bit depth "
                           f"{sorted(pdef.bit_depths)}, got {bit_depth}",
            })

    # CHECK: Bit depth is a valid VP9 value at all (8, 10, or 12)
    if bit_depth is not None and bit_depth not in (8, 10, 12):
        findings.append({
            "severity": "error",
            "code": "VP9_DEPTH_INVALID",
            "message": f"VP9 supports bit depths {{8, 10, 12}}, "
                       f"got {bit_depth}",
        })

    # CHECK: Chroma subsampling valid for profile
    # Only validate when optional fields are explicitly present — short form
    # uses default CC=00 which is not an assertion about actual chroma.
    if pdef and chroma_subsampling is not None and result.get("has_optional_fields"):
        valid_cc = VALID_CC_FOR_PROFILE.get(profile, set())
        if chroma_subsampling in (0, 1, 2, 3) and chroma_subsampling not in valid_cc:
            expected_chroma = "4:2:0 (CC 00/01)" if profile in (0, 2) else "non-4:2:0 (CC 02/03)"
            findings.append({
                "severity": "error",
                "code": "VP9_CHROMA_INVALID",
                "message": f"{pdef.name} requires {expected_chroma}, "
                           f"got CC {chroma_subsampling:02d}",
            })

    # WARNING: 12-bit depth (valid but rare in practice)
    if bit_depth == 12:
        findings.append({
            "severity": "warning",
            "code": "VP9_DEPTH_12",
            "message": "12-bit VP9 is valid per spec but rarely "
                       "deployed in practice",
        })

    # CHECK: Color parameter consistency (when optional fields present)
    if result.get("has_optional_fields"):
        cp = result.get("color_primaries", 1)
        tc = result.get("transfer_characteristics", 1)

        # PQ transfer with non-wide-gamut primaries
        if tc == 16 and cp == 1:
            findings.append({
                "severity": "warning",
                "code": "VP9_CP_TC_MISMATCH",
                "message": "PQ transfer (tc=16) with BT.709 primaries "
                           "(cp=1) is unusual — typically paired with "
                           "BT.2020 (cp=9)",
            })
        # HLG transfer with non-wide-gamut primaries
        if tc == 18 and cp == 1:
            findings.append({
                "severity": "warning",
                "code": "VP9_CP_TC_MISMATCH",
                "message": "HLG transfer (tc=18) with BT.709 primaries "
                           "(cp=1) is unusual — typically paired with "
                           "BT.2020 (cp=9)",
            })

        # Color space summary
        cp_name = result.get("color_primaries_name", "?")
        tc_name = result.get("transfer_characteristics_name", "?")
        mc_name = result.get("matrix_coefficients_name", "?")
        vr_name = result.get("video_range_name", "?")
        findings.append({
            "severity": "info",
            "code": "VP9_COLOR_SPACE",
            "message": f"Color: {cp_name} / {tc_name} / "
                       f"{mc_name} / {vr_name}",
        })

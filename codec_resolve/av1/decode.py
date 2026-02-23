"""
AV1 codec string decoder with semantic validation.

Decodes av01 strings into profile, level, tier, bit depth, and color
parameters with validation checks.

Source: AV1 Codec ISO Media File Format Binding §5 (Codecs Parameter String),
        AV1 Bitstream & Decoding Process Specification §6.4.1, Annex A.
"""
from typing import Dict, List, Optional
from .profiles import (
    AV1_PROFILE_DEFS, AV1_PROFILE_NAMES, VALID_BIT_DEPTHS,
    CHROMA_FROM_SUBSAMPLING, CHROMA_SAMPLE_POSITION_NAMES,
    BITRATE_PROFILE_FACTOR,
)
from .levels import AV1_LEVELS, AV1_LEVEL_LOOKUP, _level_name_from_idx
from ..models import (
    Chroma, COLOR_PRIMARIES, TRANSFER_CHARACTERISTICS, MATRIX_COEFFICIENTS,
)
from ..hls import strip_hls_brands


# ── Defaults for optional fields (per AV1-ISOBMFF §5) ──────────────
# "If not specified then the values listed in the table below are assumed."
_OPTIONAL_DEFAULTS = {
    "monochrome": 0,
    "chroma_subsampling": "110",  # subsampling_x=1, subsampling_y=1, CSP=0
    "color_primaries": 1,         # BT.709
    "transfer_characteristics": 1, # BT.709
    "matrix_coefficients": 1,      # BT.709
    "video_full_range_flag": 0,    # Studio swing (limited range)
}


def decode_av1(codec_string: str) -> dict:
    """
    Decode an AV1 codec string into a structured dict.

    Accepts:
        "av01.0.13M.10"                              (short: 4 mandatory fields)
        "av01.0.13M.10.0.110.09.16.09.0"             (full: 10 fields)
        "av01.0.13M.10/cdm4"                          (with HLS brand)
        "av01.0.13M.10.0.110.09.16.09.0/db4h"        (full + brand)
    """
    findings = []
    result = {
        "family": "av1",
        "findings": findings,
    }

    s = codec_string.strip()

    # ── Step 1: Strip HLS brand suffix (/brand) ────────────────────
    s, hls_brands, unknown_brands = strip_hls_brands(s)
    for ub in unknown_brands:
        findings.append({
            "severity": "warning",
            "code": "AV1_BRAND_UNKNOWN",
            "message": f"Unknown HLS brand '/{ub}' — "
                       f"not in MP4RA registry",
        })

    if hls_brands:
        result["hls_brands"] = hls_brands
    result["codec_string_full"] = codec_string.strip()

    # ── Step 2: Split and validate entry ───────────────────────────
    parts = s.split(".")
    if len(parts) < 4:
        result["codec_string"] = s
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "AV1_TOO_FEW_FIELDS",
            "message": f"Expected at least 4 dot-separated fields "
                       f"(av01.P.LLT.DD), got {len(parts)}",
        })
        return result

    entry = parts[0]
    if entry != "av01":
        result["codec_string"] = s
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "AV1_WRONG_ENTRY",
            "message": f"Expected entry 'av01', got '{entry}'",
        })
        return result

    result["entry"] = "av01"
    result["codec_string"] = s

    # ── Step 3: Parse mandatory fields ─────────────────────────────
    # P = profile (single digit)
    try:
        seq_profile = int(parts[1])
    except ValueError:
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "AV1_PROFILE_PARSE",
            "message": f"Cannot parse profile '{parts[1]}' as integer",
        })
        return result

    result["seq_profile"] = seq_profile

    if seq_profile not in AV1_PROFILE_DEFS:
        findings.append({
            "severity": "error",
            "code": "AV1_PROFILE_UNKNOWN",
            "message": f"seq_profile={seq_profile} not in {{0, 1, 2}}. "
                       f"0=Main, 1=High, 2=Professional",
        })
        result["profile_name"] = f"Unknown ({seq_profile})"
    else:
        pdef = AV1_PROFILE_DEFS[seq_profile]
        result["profile_name"] = pdef.name

    # LLT = level (two-digit zero-padded) + tier (M or H)
    llt = parts[2]
    if len(llt) < 3:
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "AV1_LEVEL_TIER_PARSE",
            "message": f"Level+tier field '{llt}' too short "
                       f"(expected LLT, e.g. '13M')",
        })
        return result

    tier_char = llt[-1].upper()
    level_str = llt[:-1]

    if tier_char not in ("M", "H"):
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "AV1_TIER_PARSE",
            "message": f"Tier character must be 'M' or 'H', got '{tier_char}'",
        })
        return result

    tier = 0 if tier_char == "M" else 1
    result["tier"] = tier
    result["tier_name"] = "Main" if tier == 0 else "High"

    try:
        seq_level_idx = int(level_str)
    except ValueError:
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "AV1_LEVEL_PARSE",
            "message": f"Cannot parse level '{level_str}' as integer",
        })
        return result

    result["seq_level_idx"] = seq_level_idx
    result["level_name"] = _level_name_from_idx(seq_level_idx)

    # Look up level in table
    level_obj = AV1_LEVEL_LOOKUP.get(seq_level_idx)
    if seq_level_idx == 31:
        findings.append({
            "severity": "warning",
            "code": "AV1_LEVEL_31",
            "message": "seq_level_idx=31: unconstrained (no level limits). "
                       "Typically used for large still images only",
        })
    elif level_obj is None:
        findings.append({
            "severity": "error",
            "code": "AV1_LEVEL_UNKNOWN",
            "message": f"seq_level_idx={seq_level_idx} is not a defined "
                       f"AV1 level. Defined: "
                       f"{sorted(AV1_LEVEL_LOOKUP.keys())} and 31",
        })

    # DD = bitDepth (two-digit zero-padded)
    try:
        bit_depth = int(parts[3])
    except ValueError:
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "AV1_DEPTH_PARSE",
            "message": f"Cannot parse bitDepth '{parts[3]}' as integer",
        })
        return result

    result["bit_depth"] = bit_depth

    # ── Step 4: Parse optional fields ──────────────────────────────
    has_optional = len(parts) > 4
    result["has_optional_fields"] = has_optional

    if has_optional:
        # Spec: all 6 optional fields must be present (or none)
        if len(parts) < 10:
            findings.append({
                "severity": "warning",
                "code": "AV1_OPTIONAL_PARTIAL",
                "message": f"Spec requires all 6 optional fields or none. "
                           f"Got {len(parts) - 4} of 6. Parsing what's present "
                           f"(Chromium also accepts partial)",
            })

        # M = monochrome
        monochrome = int(parts[4]) if len(parts) > 4 else _OPTIONAL_DEFAULTS["monochrome"]

        # CCC = chromaSubsampling
        if len(parts) > 5:
            ccc = parts[5]
            if len(ccc) >= 2:
                subsampling_x = int(ccc[0])
                subsampling_y = int(ccc[1])
                chroma_sample_position = int(ccc[2]) if len(ccc) > 2 else 0
            else:
                subsampling_x, subsampling_y, chroma_sample_position = 1, 1, 0
        else:
            subsampling_x, subsampling_y, chroma_sample_position = 1, 1, 0

        color_primaries = int(parts[6]) if len(parts) > 6 else _OPTIONAL_DEFAULTS["color_primaries"]
        transfer_characteristics = int(parts[7]) if len(parts) > 7 else _OPTIONAL_DEFAULTS["transfer_characteristics"]
        matrix_coefficients = int(parts[8]) if len(parts) > 8 else _OPTIONAL_DEFAULTS["matrix_coefficients"]
        video_full_range_flag = int(parts[9]) if len(parts) > 9 else _OPTIONAL_DEFAULTS["video_full_range_flag"]
    else:
        monochrome = _OPTIONAL_DEFAULTS["monochrome"]
        subsampling_x, subsampling_y, chroma_sample_position = 1, 1, 0
        color_primaries = _OPTIONAL_DEFAULTS["color_primaries"]
        transfer_characteristics = _OPTIONAL_DEFAULTS["transfer_characteristics"]
        matrix_coefficients = _OPTIONAL_DEFAULTS["matrix_coefficients"]
        video_full_range_flag = _OPTIONAL_DEFAULTS["video_full_range_flag"]
        findings.append({
            "severity": "info",
            "code": "AV1_OPTIONAL_DEFAULTS",
            "message": "Optional color fields not present — using defaults: "
                       "mono=0, 4:2:0, BT.709 primaries/transfer/matrix, "
                       "limited range",
        })

    result["monochrome"] = monochrome
    result["subsampling_x"] = subsampling_x
    result["subsampling_y"] = subsampling_y
    result["chroma_sample_position"] = chroma_sample_position
    result["color_primaries"] = color_primaries
    result["transfer_characteristics"] = transfer_characteristics
    result["matrix_coefficients"] = matrix_coefficients
    result["video_full_range_flag"] = video_full_range_flag

    # Resolve chroma enum
    if monochrome:
        result["chroma"] = Chroma.MONO
        result["chroma_name"] = "Monochrome"
    else:
        chroma = CHROMA_FROM_SUBSAMPLING.get((subsampling_x, subsampling_y))
        if chroma:
            result["chroma"] = chroma
            result["chroma_name"] = str(chroma)
        else:
            result["chroma"] = None
            result["chroma_name"] = f"Unknown ({subsampling_x},{subsampling_y})"

    # Resolve display names from H.273 tables
    result["color_primaries_name"] = COLOR_PRIMARIES.get(
        color_primaries, f"Unknown ({color_primaries})")
    result["transfer_characteristics_name"] = TRANSFER_CHARACTERISTICS.get(
        transfer_characteristics, f"Unknown ({transfer_characteristics})")
    result["matrix_coefficients_name"] = MATRIX_COEFFICIENTS.get(
        matrix_coefficients, f"Unknown ({matrix_coefficients})")
    result["video_range_name"] = (
        "Full (PC)" if video_full_range_flag else "Limited (studio swing)")

    # Chroma subsampling display string
    csp_name = CHROMA_SAMPLE_POSITION_NAMES.get(
        chroma_sample_position, f"Reserved ({chroma_sample_position})")
    result["chroma_subsampling_code"] = f"{subsampling_x}{subsampling_y}{chroma_sample_position}"
    result["chroma_sample_position_name"] = csp_name

    # ── Step 5: Semantic validation ────────────────────────────────
    _validate_av1(result, findings, level_obj)

    # ── Step 6: Bitrate cap ────────────────────────────────────────
    if level_obj and seq_level_idx != 31:
        bpf = BITRATE_PROFILE_FACTOR.get(seq_profile, 1.0)
        if tier == 0:
            cap_mbps = level_obj.main_mbps * bpf
        else:
            cap_mbps = (level_obj.high_mbps or level_obj.main_mbps) * bpf
        result["max_bitrate_mbps"] = cap_mbps
        result["bitrate_profile_factor"] = bpf
        findings.append({
            "severity": "info",
            "code": "AV1_BITRATE_CAP",
            "message": f"Effective max bitrate: {cap_mbps:.1f} Mbps "
                       f"({'Main' if tier == 0 else 'High'} tier × "
                       f"P{seq_profile} factor {bpf}×)",
        })

    # ── Verdict ────────────────────────────────────────────────────
    has_errors = any(f["severity"] == "error" for f in findings)
    result["verdict"] = "INVALID" if has_errors else "VALID"

    return result


def _validate_av1(result: dict, findings: list, level_obj) -> None:
    """Run semantic validation checks on parsed AV1 fields."""
    seq_profile = result.get("seq_profile")
    bit_depth = result.get("bit_depth")
    monochrome = result.get("monochrome", 0)
    tier = result.get("tier", 0)
    seq_level_idx = result.get("seq_level_idx")
    chroma = result.get("chroma")

    pdef = AV1_PROFILE_DEFS.get(seq_profile) if seq_profile is not None else None

    # CHECK: Bit depth valid for profile
    if pdef and bit_depth is not None:
        valid_depths = VALID_BIT_DEPTHS.get(seq_profile, set())
        if bit_depth not in valid_depths:
            findings.append({
                "severity": "error",
                "code": "AV1_DEPTH_INVALID",
                "message": f"Profile {seq_profile} ({pdef.name}) supports "
                           f"bit depths {sorted(valid_depths)}, "
                           f"got {bit_depth}",
            })

    # CHECK: 12-bit requires Profile 2
    if bit_depth == 12 and seq_profile is not None and seq_profile < 2:
        findings.append({
            "severity": "error",
            "code": "AV1_DEPTH_REQUIRES_P2",
            "message": f"12-bit requires Profile 2 (Professional), "
                       f"got Profile {seq_profile} ({AV1_PROFILE_NAMES.get(seq_profile, '?')})",
        })

    # CHECK: Chroma valid for profile
    if pdef and chroma is not None:
        if chroma == Chroma.MONO and not pdef.mono_allowed:
            findings.append({
                "severity": "error",
                "code": "AV1_MONO_PROFILE_MISMATCH",
                "message": f"Profile {seq_profile} ({pdef.name}) does NOT "
                           f"allow monochrome. Use Profile 0 or 2",
            })
        elif chroma != Chroma.MONO and chroma not in pdef.allowed_chroma:
            findings.append({
                "severity": "error",
                "code": "AV1_CHROMA_INVALID",
                "message": f"Profile {seq_profile} ({pdef.name}) allows "
                           f"chroma {{{', '.join(str(c) for c in pdef.allowed_chroma)}}}, "
                           f"got {chroma}",
            })

    # CHECK: 4:2:2 requires Profile 2
    if chroma == Chroma.YUV422 and seq_profile is not None and seq_profile < 2:
        findings.append({
            "severity": "error",
            "code": "AV1_422_REQUIRES_P2",
            "message": f"4:2:2 chroma requires Profile 2 (Professional), "
                       f"got Profile {seq_profile}",
        })

    # CHECK: High tier only available for levels ≥ 4.0
    if tier == 1 and level_obj is not None and level_obj.high_mbps is None:
        findings.append({
            "severity": "error",
            "code": "AV1_TIER_INVALID",
            "message": f"High tier not available for Level {level_obj.name} "
                       f"(only defined for levels ≥ 4.0)",
        })

    # CHECK: Color consistency warnings
    cp = result.get("color_primaries", 1)
    tc = result.get("transfer_characteristics", 1)
    if result.get("has_optional_fields"):
        # PQ transfer with non-wide-gamut primaries
        if tc == 16 and cp == 1:
            findings.append({
                "severity": "warning",
                "code": "AV1_CP_TC_MISMATCH",
                "message": "PQ transfer (tc=16) with BT.709 primaries (cp=1) "
                           "is unusual — typically paired with BT.2020 (cp=9)",
            })
        # HLG transfer with non-wide-gamut primaries
        if tc == 18 and cp == 1:
            findings.append({
                "severity": "warning",
                "code": "AV1_CP_TC_MISMATCH",
                "message": "HLG transfer (tc=18) with BT.709 primaries (cp=1) "
                           "is unusual — typically paired with BT.2020 (cp=9)",
            })

    # INFO: Color space summary (only when optional fields present)
    if result.get("has_optional_fields"):
        cp_name = result.get("color_primaries_name", "?")
        tc_name = result.get("transfer_characteristics_name", "?")
        mc_name = result.get("matrix_coefficients_name", "?")
        vr_name = result.get("video_range_name", "?")
        findings.append({
            "severity": "info",
            "code": "AV1_COLOR_SPACE",
            "message": f"Color: {cp_name} / {tc_name} / {mc_name} / {vr_name}",
        })

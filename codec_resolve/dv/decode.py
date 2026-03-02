"""
Dolby Vision codec string decoder.

Decodes dvh1/dvhe/dav1/dva1/dvav strings: standalone triplets,
unified DV+HEVC format, and HLS SUPPLEMENTAL-CODECS with brand suffix.

Source: ETSI TS 103 572, Dolby ISOBMFF Spec, RFC 8216bis.
"""
from typing import Dict, Optional
from ..hls import HLS_DV_BRANDS, strip_hls_brands
from .levels import DV_LEVEL_LOOKUP
from .profiles import DV_COMPAT, _dv_sub_key


DV_PROFILE_INFO = {
    # (idc, sub): (name, bl_codec, transfer, gamut, depths, el_present, status)
    #
    # Profile 5: IPTPQc2 proprietary colorspace — NOT standard YCbCr
    (5, None):  ("Profile 5 (HEVC IPTPQc2 Closed-Loop)", "HEVC (proprietary)",
                 "PQ (IPTPQc2)", "BT.2020", "10-bit", True, "Legacy (phased out)"),
    # Profile 7: Dual-layer BL+EL+RPU — 10-bit BL + 2-bit EL → 12-bit
    (7, None):  ("Profile 7 (HEVC Dual-Layer BL+EL)", "HEVC Main 10 (BL) + HEVC EL",
                 "PQ", "BT.2020", "12-bit (10+2)", True, "Current (UHD Blu-ray)"),
    # Profile 8 sub-profiles
    (8, 1):     ("Profile 8.1 (HDR10-Compat)", "HEVC Main 10", "PQ",
                 "BT.2020/P3", "10-bit", False, "Current ★"),
    (8, 2):     ("Profile 8.2 (SDR-Compat)", "HEVC Main 10", "SDR",
                 "BT.709", "10-bit", False, "Current"),
    (8, 4):     ("Profile 8.4 (HLG-Compat)", "HEVC Main 10", "HLG",
                 "BT.2020", "10-bit", False, "Current (Apple/broadcast)"),
    (8, None):  ("Profile 8 (sub-profile unknown)", "HEVC Main 10", "—",
                 "—", "10-bit", False, "Current"),
    # Profile 9: AVC base (H.264)
    (9, None):  ("Profile 9 (AVC + RPU)", "AVC (H.264) High Profile", "SDR",
                 "BT.709", "8-bit", False, "Current (AVC legacy)"),
    # Profile 10: AV1 base — NOT HEVC
    (10, None): ("Profile 10 (AV1 + RPU)", "AV1 Main 10", "PQ",
                 "BT.2020", "10-bit", False, "Current (royalty-free)"),
    # Profile 20: MV-HEVC spatial/3D
    (20, None): ("Profile 20 (MV-HEVC Spatial)", "MV-HEVC (Multiview)", "PQ",
                 "BT.2020", "10-bit", False, "Current ★ (Vision Pro)"),
    # Legacy AVC profiles
    (4, None):  ("Profile 4 (AVC BL + HEVC EL)", "AVC + HEVC", "SDR",
                 "BT.709", "8-bit", True, "Deprecated"),
    (1, None):  ("Profile 1 (AVC Dual-Layer)", "AVC", "SDR",
                 "BT.709", "8-bit", True, "Deprecated"),
    (2, None):  ("Profile 2 (AVC Single-Layer)", "AVC", "SDR",
                 "BT.709", "8-bit", False, "Deprecated"),
    (3, None):  ("Profile 3 (AVC Dual-Layer Variant)", "AVC", "SDR",
                 "BT.709", "8-bit", True, "Deprecated"),
}



def decode_dv(codec_string: str) -> dict:
    """
    Decode a Dolby Vision codec string into all its component fields.

    Supports THREE formats:

    1. Standalone DV triplet (HLS codecs= attribute):
       "dvh1.08.06" or "dav1.10.09"
       → 3 dot-separated components: <entry>.<profile:02d>.<level:02d>

    2. Unified DV+HEVC string (container/manifest):
       "dvh1.08.06.H153.B0.00.00.00.00.00"
       → DV triplet + HEVC tier/level + constraint bytes
       The entry wraps the HEVC base layer, so HEVC parameters
       follow the DV profile/level directly.

    3. HLS SUPPLEMENTAL-CODECS with brand (RFC 8216bis §4.4.6.2):
       "dvh1.08.06/db4h" or "dvh1.08.07/db4h"
       → DV triplet + slash-separated ISOBMFF compatibility brand(s)
       The brand identifies the backward-compatible fallback format
       and disambiguates DV Profile 8 sub-profiles:
         /db1p → compat_id 1 (HDR10/PQ cross-compatible)
         /db4h → compat_id 4 (HLG cross-compatible)

    When the unified format is detected, the embedded HEVC parameters
    are automatically decoded and cross-validated.

    Output: dict with entry, profile, level, capabilities, and
            optionally embedded_hevc (decoded HEVC dict),
            embedded_validation (cross-validation result),
            and hls_brands (list of brand info dicts).
    """
    # ── HLS brand stripping (RFC 8216bis §4.4.6.2) ──
    # SUPPLEMENTAL-CODECS format: "codec_format/brand[/brand...]"
    # Strip brand suffix before dot-parsing, store for later validation
    codec_string, hls_brands, _unknown = strip_hls_brands(codec_string)

    parts = codec_string.split(".")

    # Determine format: 3 parts = standalone, >3 = unified with HEVC
    if len(parts) < 3:
        raise ValueError(
            f"Invalid DV codec string: '{codec_string}'. "
            f"Expected at least 3 dot-separated components: "
            f"<entry>.<profile:02d>.<level:02d>")

    # Parse the DV triplet (first 3 components)
    dv_entry = parts[0]
    dv_profile_str = parts[1]
    dv_level_str = parts[2]

    findings = []
    result = {"codec_string": codec_string, "family": "dv", "findings": findings}

    # Always set codec_string_full
    result["codec_string_full"] = codec_string.strip()

    # Store HLS brand info if present
    if hls_brands:
        result["hls_brands"] = hls_brands
        # Reconstruct the full original string for display
        brand_suffix = "/".join(b["brand"] for b in hls_brands)
        result["codec_string_full"] = f"{codec_string}/{brand_suffix}"

    # 1. Entry point
    entry_info = {
        "dvhe": "HEVC base layer, RPU in-band (NAL units — DASH/TS)",
        "dvh1": "HEVC base layer, RPU out-of-band (sample description — HLS/MP4)",
        "dva1": "AVC base layer, RPU out-of-band (sample description — HLS/MP4)",
        "dvav": "AVC base layer, RPU in-band (NAL units)",
        "dav1": "AV1 base layer, RPU out-of-band (sample description)",
        # Non-standard entries (Profile 5 only)
        "dvc1": "HEVC base layer, deprecated pre-standard DV container tag",
        "dvhp": "HEVC base layer, OMAF/VR DV container tag (ISO/IEC 23090-2)",
    }
    if dv_entry not in entry_info:
        raise ValueError(f"Unknown DV entry: '{dv_entry}'. "
                         f"Expected: {', '.join(entry_info.keys())}")

    # Warn on non-standard entries
    _NONSTANDARD_ENTRIES = {
        "dvc1": ("Deprecated pre-standard DV FourCC. "
                 "Use dvhe (in-band) or dvh1 (out-of-band) instead."),
        "dvhp": ("OMAF/VR DV FourCC (ISO/IEC 23090-2). "
                 "Not part of standard ETSI TS 103 572 DV signaling."),
    }
    if dv_entry in _NONSTANDARD_ENTRIES:
        findings.append({
            "severity": "warning",
            "code": "DV_NONSTANDARD_ENTRY",
            "message": f"Non-standard entry '{dv_entry}': "
                       f"{_NONSTANDARD_ENTRIES[dv_entry]}",
        })
    result["entry"] = dv_entry
    result["entry_meaning"] = entry_info[dv_entry]
    if dv_entry in ("dvhe", "dvh1", "dvc1", "dvhp"):
        result["base_layer_codec"] = "HEVC"
    elif dv_entry in ("dva1", "dvav"):
        result["base_layer_codec"] = "AVC"
    elif dv_entry == "dav1":
        result["base_layer_codec"] = "AV1"

    # 2. Profile IDC
    profile_idc = int(dv_profile_str)
    result["profile_idc"] = profile_idc

    # Look up profile info
    info = DV_PROFILE_INFO.get((profile_idc, None))
    if profile_idc == 8:
        result["profile_name"] = "Profile 8 (single-layer + RPU)"
        result["sub_profiles"] = {
            "8.1": "HDR10-compatible (PQ + BT.2020/P3, 10-bit)",
            "8.2": "SDR-compatible (SDR + BT.709, 10-bit)",
            "8.4": "HLG-compatible (HLG + BT.2020, 10-bit)",
        }
        result["note"] = ("Sub-profile (8.1/8.2/8.4) is determined by "
                          "bl_signal_compatibility_id in the RPU, "
                          "not visible in the codec string alone")
        result["enhancement_layer"] = False
        result["status"] = "Current ★ (dominant streaming profile)"
        result["cross_compat"] = "HEVC Main 10 (HDR10/SDR/HLG depending on sub-profile)"
    elif info:
        name, bl, transfer, gamut, depths, el, status = info
        result["profile_name"] = name
        result["base_layer_profile"] = bl
        result["transfer_function"] = transfer
        result["color_gamut"] = gamut
        result["bit_depth"] = depths
        result["enhancement_layer"] = el
        result["status"] = status

        if profile_idc == 5:
            result["cross_compat"] = "NONE — IPTPQc2 closed-loop"
            result["colorspace"] = "IPTPQc2 (proprietary)"
            findings.append({
                "severity": "warning",
                "code": "DV_PROPRIETARY_COLORSPACE",
                "message": "Standard HEVC decoders will produce "
                           "green/purple distortion. DV decoder required.",
            })
        elif profile_idc == 7:
            result["cross_compat"] = ("HEVC Main 10 (BL only — hardware fallback). "
                                      "Full DV requires BL+EL dual decode")
            result["layer_detail"] = "10-bit BL + 2-bit EL → 12-bit reconstructed"
        elif profile_idc == 9:
            result["cross_compat"] = "AVC (H.264) High Profile — 8-bit SDR fallback"
        elif profile_idc == 10:
            result["cross_compat"] = "AV1 Main 10 (NOT HEVC)"
        elif profile_idc == 20:
            result["cross_compat"] = ("2D HEVC Main 10 (single-eye fallback). "
                                      "Full spatial requires MV-HEVC decoder")
    else:
        result["profile_name"] = f"Unknown profile {profile_idc}"

    # Standard contract: ensure numeric bit_depth and chroma
    # DV stores descriptive strings like "10-bit" or "12-bit (10+2)"
    _bd = result.get("bit_depth")
    if isinstance(_bd, str):
        # Extract first integer from "10-bit" or "12-bit (10+2)"
        import re
        _m = re.match(r"(\d+)", _bd)
        result["bit_depth"] = int(_m.group(1)) if _m else 10
    elif _bd is None:
        # Profile 8 doesn't set bit_depth directly — all sub-profiles are 10-bit
        result["bit_depth"] = 10
    if "chroma" not in result:
        result["chroma"] = "4:2:0"

    # Validate entry matches profile's expected base codec
    compat = DV_COMPAT.get(_dv_sub_key(profile_idc))
    if not compat:
        compat = DV_COMPAT.get(str(profile_idc))
    if compat and dv_entry not in compat.entries:
        findings.append({
            "severity": "warning",
            "code": "DV_ENTRY_MISMATCH",
            "message": f"Entry '{dv_entry}' is unexpected for Profile {profile_idc} "
                       f"({compat.base_codec} base). Expected: "
                       f"{', '.join(sorted(compat.entries))}",
        })

    # 3. Level
    level_id = int(dv_level_str)
    result["level_id"] = level_id
    result["level_idc"] = level_id         # standard contract alias
    result["level_name"] = str(level_id)   # standard contract alias

    lv = DV_LEVEL_LOOKUP.get(level_id)
    if lv:
        result["level_max_width"] = lv.max_width
        result["level_max_height"] = lv.max_height
        result["level_max_fps"] = lv.max_fps
        result["max_fps"] = lv.max_fps                            # standard contract
        result["level_max_pps"] = lv.max_pps
        result["level_max_bitrate_main"] = f"{lv.max_br_main:,} kbps"
        result["max_bitrate_kbps"] = lv.max_br_main               # standard contract
        if lv.max_br_high > 0:
            result["level_max_bitrate_high"] = f"{lv.max_br_high:,} kbps"
        result["level_max_resolution"] = f"{lv.max_width}×{lv.max_height}@{lv.max_fps:g}fps"
        result["max_resolution"] = f"{lv.max_width}x{lv.max_height}"  # standard contract
    else:
        result["level_max_resolution"] = f"Unknown (level {level_id})"
        result["max_resolution"] = None
        result["max_fps"] = None
        result["max_bitrate_kbps"] = None

    # ── 3b. HLS Brand Inference (RFC 8216bis §4.4.6.2) ──────────
    # If ISOBMFF brands are present (from SUPPLEMENTAL-CODECS), use
    # them to infer the bl_signal_compatibility_id for Profile 8.
    # The brand disambiguates the sub-profile that is normally hidden
    # inside the RPU bitstream.
    if hls_brands:
        brand_findings = []
        for bi in hls_brands:
            brand_code = bi["brand"].lower()
            brand_def = HLS_DV_BRANDS.get(brand_code)
            if brand_def:
                # Validate brand applies to this DV profile
                if brand_def.dv_profiles and profile_idc not in brand_def.dv_profiles:
                    brand_findings.append({
                        "code": "BRAND_PROFILE_MISMATCH",
                        "severity": "warning",
                        "message": (
                            f"Brand '{bi['brand']}' ({brand_def.description}) "
                            f"is not expected for DV Profile {profile_idc}. "
                            f"Expected profiles: "
                            f"{', '.join(str(p) for p in sorted(brand_def.dv_profiles))}")
                    })
                # For Profile 8: infer bl_compat_id from brand
                if profile_idc == 8 and brand_def.inferred_compat_id is not None:
                    result["bl_compat_id"] = brand_def.inferred_compat_id
                    compat_names = {
                        1: "8.1 (HDR10-compatible)",
                        2: "8.2 (SDR-compatible)",
                        4: "8.4 (HLG-compatible)",
                    }
                    inferred_name = compat_names.get(
                        brand_def.inferred_compat_id,
                        f"8.? (compat_id={brand_def.inferred_compat_id})")
                    result["brand_inferred_subprofile"] = inferred_name
                    brand_findings.append({
                        "code": "BRAND_SUBPROFILE_INFERRED",
                        "severity": "info",
                        "message": (
                            f"Brand '{bi['brand']}' identifies sub-profile "
                            f"{inferred_name} "
                            f"(bl_signal_compatibility_id="
                            f"{brand_def.inferred_compat_id})")
                    })
        if brand_findings:
            result["brand_findings"] = brand_findings

    # ── 4. Unified Format: Embedded HEVC Parameters ─────────────
    # If >3 parts, the remaining components form the HEVC tier/level
    # and constraint bytes. The DV entry (dvh1/dvhe) wraps the HEVC
    # base layer — so the HEVC codec string is reconstructed by
    # replacing the DV entry with the corresponding HEVC entry:
    #   dvh1 → hvc1 (both out-of-band / sample description)
    #   dvhe → hev1 (both in-band / NAL units)
    if len(parts) > 3 and dv_entry in ("dvh1", "dvhe", "dvc1", "dvhp"):
        # Map DV entry → HEVC entry per MPEG-4 Part 15
        hevc_entry = "hvc1" if dv_entry == "dvhe" else "hev1"

        # The embedded HEVC string needs profile_idc + compat_flags
        # which aren't in the unified string explicitly.
        # Infer from DV profile's expected HEVC profile:
        if compat and compat.hevc_profiles:
            inferred_hevc_profile = sorted(compat.hevc_profiles)[-1]
        else:
            inferred_hevc_profile = 2  # Default Main 10

        # Reconstruct HEVC constraint compatibility flags
        # Profile 2 (Main 10) → compat flag 4, Profile 1 → compat flag 6
        hevc_compat_map = {1: "6", 2: "4", 4: "10", 5: "20",
                           9: "202", 10: "406", 11: "820"}
        hevc_compat = hevc_compat_map.get(inferred_hevc_profile, "4")

        # Reconstruct: hvc1.<profile>.<compat>.<tier+level>.<constraints...>
        hevc_parts = [hevc_entry, str(inferred_hevc_profile),
                      hevc_compat] + parts[3:]
        hevc_string = ".".join(hevc_parts)

        result["unified_format"] = True
        result["embedded_hevc_string"] = hevc_string

        try:
            hevc_decoded = decode_hevc(hevc_string)
            result["embedded_hevc"] = hevc_decoded

            # Auto cross-validate
            validation = validate_hybrid(hevc_decoded, result)

            # Propagate embedded HEVC validation errors into the
            # unified verdict — if the base layer itself is invalid,
            # the unified string cannot be valid either.
            hevc_findings = hevc_decoded.get("findings", [])
            for f in hevc_findings:
                if f["severity"] == "error":
                    validation["issues"].append(
                        f"[HEVC:{f['code']}] {f['message']}")
                    validation["valid"] = False
                elif f["severity"] == "warning":
                    validation["notes"].append(
                        f"⚠ [HEVC:{f['code']}] {f['message']}")

            result["embedded_validation"] = validation
        except (ValueError, KeyError) as e:
            result["embedded_hevc_error"] = str(e)
    elif len(parts) > 3:
        # Non-HEVC DV entry with extra parts — likely malformed
        findings.append({
            "severity": "warning",
            "code": "DV_EXTRA_PARTS",
            "message": f"DV entry '{dv_entry}' has {len(parts)} components but "
                       f"only 3 expected. Extra parts ignored: "
                       f"{'.'.join(parts[3:])}",
        })

    # ── Verdict ────────────────────────────────────────────────────
    has_errors = any(f["severity"] == "error" for f in findings)
    result["verdict"] = "INVALID" if has_errors else "VALID"

    return result


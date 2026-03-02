"""
AVC/H.264 codec string decoder with semantic validation.

Decodes avc1/avc3 strings per ISO/IEC 14496-15 §5.3.1.
Format: avc1.PPCCLL (hex triplet) or avc3.PPCCLL.

Source: ISO/IEC 14496-15 §5.3.1, ITU-T H.264 §7.4.2.1.
"""
from .profiles import (
    AVC_PROFILE_DEFS, AVC_PROFILE_NAMES, AVC_VALID_PROFILE_IDCS,
    parse_constraint_flags, get_reserved_bits, derive_constrained_profile,
)
from .levels import AVC_LEVEL_LOOKUP, AVC_VALID_LEVEL_IDCS, BITRATE_PROFILE_MULTIPLIER as PROFILE_BR_MULT
from ..hls import strip_hls_brands


_VALID_ENTRIES = {"avc1", "avc3"}


def decode_avc(codec_string: str) -> dict:
    """Decode an AVC codec string into a structured dict.

    Accepts:
        "avc1.640028"        High L4.0
        "avc1.42E01E"        Baseline L3.0
        "avc1.42C01E"        Constrained Baseline L3.0
        "avc3.640028"        avc3 variant

    Returns dict with keys:
        family, entry, entry_meaning, codec_string, codec_string_full,
        profile_idc, profile_name, constraint_byte, constraint_flags,
        level_idc, level_name, bit_depth, chroma, max_bitrate_kbps,
        findings, verdict
    """
    findings = []
    result = {
        "family": "avc",
        "findings": findings,
    }

    s = codec_string.strip()

    # ── Step 1: Strip HLS brand suffix ────────────────────────
    s, hls_brands, unknown_brands = strip_hls_brands(s)
    for ub in unknown_brands:
        findings.append({
            "severity": "warning",
            "code": "AVC_BRAND_UNKNOWN",
            "message": f"Unknown HLS brand '/{ub}' — not in MP4RA registry",
        })
    if hls_brands:
        result["hls_brands"] = hls_brands
    result["codec_string_full"] = codec_string.strip()

    # ── Step 2: Split on dot → entry + hex triplet ────────────
    parts = s.split(".")
    if len(parts) < 2:
        findings.append({
            "severity": "error",
            "code": "AVC_FIELD_COUNT",
            "message": f"AVC codec string needs entry.PPCCLL, got {len(parts)} part(s)",
        })
        result["codec_string"] = s
        result["verdict"] = "INVALID"
        return result

    if len(parts) > 2:
        findings.append({
            "severity": "error",
            "code": "AVC_FIELD_COUNT",
            "message": f"AVC codec string should have exactly 2 dot-separated parts "
                       f"(entry.PPCCLL), got {len(parts)}",
        })
        result["codec_string"] = s
        result["verdict"] = "INVALID"
        return result

    entry = parts[0].lower()
    hex_triplet = parts[1]

    if entry not in _VALID_ENTRIES:
        findings.append({
            "severity": "error",
            "code": "AVC_ENTRY_UNKNOWN",
            "message": f"Expected 'avc1' or 'avc3', got '{entry}'",
        })
        result["codec_string"] = s
        result["entry"] = entry
        result["verdict"] = "INVALID"
        return result

    result["entry"] = entry
    result["entry_meaning"] = (
        "SPS/PPS in sample description (out-of-band)"
        if entry == "avc1"
        else "SPS/PPS in access units (in-band)")
    result["codec_string"] = s

    # ── Step 3: Validate hex triplet ──────────────────────────
    if len(hex_triplet) != 6:
        findings.append({
            "severity": "error",
            "code": "AVC_HEX_FORMAT",
            "message": f"Hex triplet must be exactly 6 characters (PPCCLL), "
                       f"got {len(hex_triplet)}: '{hex_triplet}'",
        })
        result["verdict"] = "INVALID"
        return result

    # Validate all hex characters
    try:
        int(hex_triplet, 16)
    except ValueError:
        findings.append({
            "severity": "error",
            "code": "AVC_HEX_FORMAT",
            "message": f"Hex triplet contains non-hex characters: '{hex_triplet}'",
        })
        result["verdict"] = "INVALID"
        return result

    # ── Step 4: Parse the three bytes ─────────────────────────
    profile_idc = int(hex_triplet[0:2], 16)
    constraint_byte = int(hex_triplet[2:4], 16)
    level_idc = int(hex_triplet[4:6], 16)

    result["profile_idc"] = profile_idc
    result["constraint_byte"] = constraint_byte
    result["level_idc"] = level_idc

    # ── Step 5: Profile lookup ────────────────────────────────
    pdef = AVC_PROFILE_DEFS.get(profile_idc)
    if pdef:
        result["profile_name"] = pdef.name
        result["bit_depth"] = pdef.max_bit_depth
        result["chroma"] = str(max(pdef.allowed_chroma,
                                   key=lambda c: c.value))
    else:
        result["profile_name"] = f"Unknown ({profile_idc})"
        findings.append({
            "severity": "error",
            "code": "AVC_PROFILE_UNKNOWN",
            "message": f"profile_idc {profile_idc} (0x{profile_idc:02X}) "
                       f"not in known set: "
                       f"{', '.join(f'{k} ({v})' for k, v in sorted(AVC_PROFILE_NAMES.items()))}",
        })

    # ── Step 6: Constraint flags ──────────────────────────────
    flags = parse_constraint_flags(constraint_byte)
    result["constraint_flags"] = flags

    reserved = get_reserved_bits(constraint_byte)
    if reserved != 0:
        findings.append({
            "severity": "error",
            "code": "AVC_RESERVED_BITS",
            "message": f"Constraint byte bits 1-0 (reserved_zero_2bits) must be 0, "
                       f"got {reserved} (byte=0x{constraint_byte:02X})",
        })

    # Derive constrained profile
    derived = derive_constrained_profile(profile_idc, flags)
    if derived:
        result["constrained_profile"] = derived
        findings.append({
            "severity": "info",
            "code": "AVC_CONSTRAINED_PROFILE",
            "message": f"Derived profile: {derived}",
        })

    # ── Step 7: Level lookup ──────────────────────────────────
    # Handle Level 1b: level_idc=11 + constraint_set3_flag, or level_idc=9
    actual_level_idc = level_idc
    is_level_1b = False

    if level_idc == 11 and flags.get("set3"):
        # Level 1b via constraint_set3_flag
        actual_level_idc = 9  # Our internal representation for 1b
        is_level_1b = True
    elif level_idc == 9:
        is_level_1b = True

    level_obj = AVC_LEVEL_LOOKUP.get(actual_level_idc)
    if level_obj:
        result["level_name"] = level_obj.name
        result["level_max_resolution"] = level_obj.example
        result["level_max_fs"] = level_obj.max_fs
        result["level_max_mbps"] = level_obj.max_mbps
    else:
        result["level_name"] = f"Unknown ({level_idc})"
        findings.append({
            "severity": "error",
            "code": "AVC_LEVEL_UNKNOWN",
            "message": f"level_idc {level_idc} (0x{level_idc:02X}) "
                       f"not in defined AVC levels",
        })

    if is_level_1b:
        findings.append({
            "severity": "info",
            "code": "AVC_LEVEL_1B",
            "message": "Level 1b detected"
                       + (" via constraint_set3_flag on level_idc=11"
                          if level_idc == 11 else
                          " via alternate level_idc=9"),
        })

    # ── Step 8: Semantic validation ───────────────────────────
    _validate_avc(result, findings, pdef, level_obj)

    # ── Verdict ───────────────────────────────────────────────
    has_errors = any(f["severity"] == "error" for f in findings)
    result["verdict"] = "INVALID" if has_errors else "VALID"

    return result


def _validate_avc(result: dict, findings: list,
                  pdef, level_obj) -> None:
    """Run semantic validation checks on parsed AVC fields."""
    profile_idc = result.get("profile_idc")
    constraint_byte = result.get("constraint_byte", 0)
    flags = result.get("constraint_flags", {})

    # ── CHECK: Constraint flag consistency with profile ────────
    # set0 = Baseline-compatible, set1 = Main-compatible,
    # set2 = Extended-compatible
    if profile_idc == 100 and flags.get("set0"):
        # High profile claiming Baseline compatibility is unusual
        # (High is a superset, but not backward-compatible with Baseline)
        findings.append({
            "severity": "warning",
            "code": "AVC_CONSTRAINT_MISMATCH",
            "message": "constraint_set0_flag=1 on High profile — "
                       "High is not Baseline-compatible "
                       "(Baseline lacks CABAC, 8×8 transform)",
        })

    if profile_idc in (110, 122, 244) and flags.get("set0"):
        findings.append({
            "severity": "warning",
            "code": "AVC_CONSTRAINT_MISMATCH",
            "message": f"constraint_set0_flag=1 on profile {profile_idc} — "
                       f"high-depth profiles are not Baseline-compatible",
        })

    # set3 on profiles other than Baseline/Main/Extended usually means Intra-only
    if flags.get("set3") and profile_idc in (100, 110, 122, 244):
        # High profiles with set3 = intra-only variant
        result.setdefault("constrained_profile", None)
        if not result["constrained_profile"]:
            intra_name = f"{AVC_PROFILE_NAMES.get(profile_idc, '?')} Intra"
            result["constrained_profile"] = intra_name
            findings.append({
                "severity": "info",
                "code": "AVC_CONSTRAINED_PROFILE",
                "message": f"Derived profile: {intra_name} "
                           f"(constraint_set3_flag on High-family profile)",
            })

    # ── CHECK: Entry type info ────────────────────────────────
    entry = result.get("entry", "")
    findings.append({
        "severity": "info",
        "code": "AVC_ENTRY_TYPE",
        "message": result.get("entry_meaning",
                              f"{entry} entry type"),
    })

    # ── CHECK: Max bitrate for level × profile ────────────────
    if pdef and level_obj:
        multiplier = PROFILE_BR_MULT.get(profile_idc, 1.0)
        max_br = int(level_obj.max_br_kbps * multiplier)
        result["max_bitrate_kbps"] = max_br
        findings.append({
            "severity": "info",
            "code": "AVC_BITRATE_CAP",
            "message": f"Max bitrate: {max_br:,} kbps "
                       f"(Level {level_obj.name} × "
                       f"{pdef.name} {multiplier}×)",
        })

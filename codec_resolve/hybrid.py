"""
Hybrid cross-validation: base layer + Dolby Vision codec pair analysis.

Validates the contract between base layer (HEVC or AV1) and DV enhancement,
including checks across profile, level, throughput, bitrate, entry points,
EL/INBLD, and HLS brand consistency.
"""
from typing import Dict, List, Optional
from .models import Chroma
from .hls import HLS_DV_BRANDS
from .hevc.levels import HEVC_LEVELS, HEVCLevel
from .hevc.decode import decode_hevc, HEVC_LEVEL_LOOKUP
from .dv.levels import DV_LEVEL_LOOKUP, DV_TO_HEVC_LEVEL_IDC, DV_TO_AV1_LEVEL_IDX, DVLevel
from .dv.profiles import DV_COMPAT, DVCompat, _dv_sub_key, METADATA_DELIVERY
from .registry import CODEC_ENTRIES
from .dv.decode import decode_dv
from .av1.decode import decode_av1
from .av1.levels import AV1_LEVEL_LOOKUP
from .vp9.decode import decode_vp9


def validate_hybrid(hevc_decoded: dict, dv_decoded: dict) -> dict:
    """
    Cross-validate a decoded HEVC + DV pair.

    Returns dict with:
      valid: bool
      issues: list of compatibility violations
      notes: list of informational observations
      compat: DVCompat rule (if matched)
      hybrid_string: combined "hevc, dv" format
    """
    dv_display = dv_decoded.get("codec_string_full", dv_decoded["codec_string"])
    result = {
        "valid": True,
        "issues": [],
        "notes": [],
        "compat": None,
        "hybrid_string": f"{hevc_decoded['codec_string']}, {dv_display}",
    }

    dv_idc = dv_decoded.get("profile_idc")
    dv_bl_compat = dv_decoded.get("bl_compat_id")

    # Find compatibility rule
    # Pass bl_compat_id as-is (None = unknown from decode, 0 = explicit no-fallback)
    sub_key = _dv_sub_key(dv_idc, dv_bl_compat)
    compat = DV_COMPAT.get(sub_key)

    if not compat:
        compat = DV_COMPAT.get(str(dv_idc))

    if not compat:
        result["issues"].append(
            f"No compatibility rule for DV profile {dv_idc} — "
            f"cannot validate base layer")
        result["valid"] = False
        return result

    result["compat"] = compat

    # --- Check if this DV profile even uses HEVC as base ---
    if compat.base_codec == "AV1":
        result["issues"].append(
            f"DV Profile {dv_idc} uses AV1 base layer (entry 'dav1'), "
            f"not HEVC. This is not a valid HEVC hybrid pairing")
        result["valid"] = False
        return result

    if compat.base_codec == "AVC":
        result["issues"].append(
            f"DV Profile {dv_idc} uses AVC (H.264) base layer "
            f"(entry 'dvav'/'dva1'), not HEVC")
        result["valid"] = False
        return result

    if compat.base_codec == "MV-HEVC":
        result["notes"].append({"severity": "info", "message":
            f"DV Profile {dv_idc} uses MV-HEVC (multiview) — "
            f"base HEVC string describes the primary view. "
            f"Full stereoscopic decode requires MV-HEVC capability"})

    # --- Profile 5: IPTPQc2 closed-loop warning ---
    # Profile 5 uses a proprietary colorspace. The HEVC base layer is
    # NOT standard YCbCr — decoding without the DV reshaping metadata
    # produces green/purple distortion. This is informational; the
    # profile check below enforces the Main 10 requirement.
    if dv_idc == 5:
        result["notes"].append({"severity": "warning", "message":
            f"DV Profile 5 uses proprietary IPTPQc2 colorspace — "
            f"the HEVC base layer is NOT standard YCbCr. "
            f"Decoding as standard HEVC Main 10 will produce "
            f"green/purple color distortion. "
            f"No standard HDR/SDR fallback is possible"})

    # --- Check HEVC profile ---
    if compat.hevc_profiles:
        hevc_profile = hevc_decoded.get("profile_idc")
        if hevc_profile not in compat.hevc_profiles:
            result["issues"].append(
                f"DV {compat.dv_sub} requires {compat.base_label} "
                f"(profile {sorted(compat.hevc_profiles)}), "
                f"but base is profile {hevc_profile} "
                f"({hevc_decoded.get('profile_name', '?')})")
            result["valid"] = False
        else:
            result["notes"].append({"severity": "pass", "message":
                f"HEVC profile {hevc_profile} "
                f"({hevc_decoded.get('profile_name', '?')}) "
                f"matches DV {compat.dv_sub} requirement "
                f"({compat.base_label})"})

    # --- Check HEVC level vs DV level capacity (BIDIRECTIONAL) ---
    hevc_level_idc = hevc_decoded.get("level_idc", 0)
    dv_level_id = dv_decoded.get("level_id", 0)

    dv_lv = DV_LEVEL_LOOKUP.get(dv_level_id)
    hevc_lv = HEVC_LEVEL_LOOKUP.get(hevc_level_idc)

    if dv_lv and hevc_lv:
        dv_pps = dv_lv.max_width * dv_lv.max_height * dv_lv.max_fps
        dv_max_pixels = dv_lv.max_width * dv_lv.max_height
        hevc_max_pixels = hevc_lv.max_luma_ps

        # All four checks form a SINGLE priority chain.
        # Only one outcome (fail/warn/pass) is reported.

        # CHECK 1: Can DV RPU processor handle HEVC's frame size?
        # The DV level constrains the RPU metadata buffer allocation.
        # RPU processes per-block tone-mapping metadata sized for
        # max_width × max_height of the DV level. If the HEVC decoder
        # delivers a frame larger than the DV RPU's buffer grid,
        # the metadata addressing overflows.
        #
        # Allow 10% tolerance: HEVC max_luma_ps is slightly larger than
        # the standard resolution for each tier (e.g. L5.0 = 8,912,896
        # vs 4K = 8,294,400 = 1.07×) to accommodate non-standard aspects.
        if hevc_max_pixels > dv_max_pixels * 1.1:
            # Determine resolution names for clear error message
            res_names = {
                (1280, 720): "720p",
                (1920, 1080): "1080p (Full HD)",
                (3840, 2160): "4K (UHD)",
                (7680, 4320): "8K",
            }
            dv_res = res_names.get((dv_lv.max_width, dv_lv.max_height),
                                  f"{dv_lv.max_width}×{dv_lv.max_height}")
            hevc_res = "unknown"
            # Derive HEVC resolution class from max_luma_ps
            for (w, h), name in sorted(res_names.items(),
                                       key=lambda x: x[0][0] * x[0][1],
                                       reverse=True):
                if hevc_max_pixels >= w * h * 0.9:
                    hevc_res = name
                    break

            ratio = hevc_max_pixels / dv_max_pixels
            result["issues"].append(
                f"Level mismatch — HEVC L{hevc_lv.number} can deliver "
                f"frames up to {hevc_max_pixels:,} pixels "
                f"({hevc_res}), but DV L{dv_level_id:02d} RPU "
                f"metadata buffers are sized for "
                f"{dv_lv.max_width}×{dv_lv.max_height} = "
                f"{dv_max_pixels:,} pixels ({dv_res}). "
                f"The HEVC decoder would push {ratio:.1f}× more pixels "
                f"than the DV RPU can address, causing metadata overflow")
            result["valid"] = False

        # CHECK 2: Can HEVC decode what DV requires?
        # "Is the HEVC decoder fast enough for DV's throughput?"
        elif hevc_lv.max_luma_sps < dv_pps:
            result["issues"].append(
                f"HEVC Level {hevc_lv.number} "
                f"({hevc_lv.max_luma_sps:,.0f} samples/s) cannot decode "
                f"DV Level {dv_level_id:02d} content "
                f"(up to {dv_lv.max_width}×{dv_lv.max_height}@"
                f"{dv_lv.max_fps:g}fps = {dv_pps:,.0f} samples/s)")
            result["valid"] = False

        # CHECK 3: Does DV throughput match HEVC throughput?
        # Even if frame SIZE fits, DV must handle the frame RATE.
        # Example: HEVC L5.0 used for 1080p@120 → DV L05 (1080p@60)
        # would have matching frame sizes but half the throughput.
        # Only warn at 2× mismatch — HEVC levels are inherently more
        # generous than DV levels in samples/s for the same tier.
        elif hevc_lv.max_luma_sps > dv_pps * 2.0:
            hevc_tput = hevc_lv.max_luma_sps
            result["notes"].append({"severity": "warning", "message":
                f"HEVC L{hevc_lv.number} throughput "
                f"({hevc_tput:,.0f} samples/s) exceeds DV L"
                f"{dv_level_id:02d} ({dv_pps:,.0f} samples/s) by "
                f"{hevc_tput / dv_pps:.1f}×. DV RPU frame size is "
                f"sufficient, but HEVC may deliver frames faster "
                f"than the DV level's rated throughput"})

        # CHECK 4: All good — levels match in both directions
        else:
            headroom = hevc_lv.max_luma_sps / dv_pps if dv_pps > 0 else 999
            if headroom > 1.5:
                result["notes"].append({"severity": "pass", "message":
                    f"HEVC L{hevc_lv.number} has headroom over DV L"
                    f"{dv_level_id:02d} — decoder supports up to "
                    f"{hevc_lv.max_luma_sps:,.0f} samples/s, "
                    f"DV content caps at {dv_pps:,.0f} "
                    f"({headroom:.1f}× headroom)"})
            else:
                result["notes"].append({"severity": "pass", "message":
                    f"HEVC L{hevc_lv.number} sufficient for DV L"
                    f"{dv_level_id:02d} content"})

    # --- DV Level → HEVC Level IDC direct mapping (FF-1) ---
    # Beyond throughput math, validate the STANDARD mapping.
    # Each DV level has a minimum expected HEVC level IDC.
    # If the HEVC IDC is below this, the pairing is non-standard
    # even if throughput happens to pass (e.g., different aspect ratios).
    if dv_lv:
        expected_idc = DV_TO_HEVC_LEVEL_IDC.get(dv_level_id)
        if expected_idc and hevc_level_idc > 0:
            expected_lv = HEVC_LEVEL_LOOKUP.get(expected_idc)
            if hevc_level_idc < expected_idc:
                exp_name = f"L{expected_lv.number}" if expected_lv else f"IDC {expected_idc}"
                curr_lv = HEVC_LEVEL_LOOKUP.get(hevc_level_idc)
                curr_name = f"L{curr_lv.number}" if curr_lv else f"IDC {hevc_level_idc}"
                result["issues"].append(
                    f"DV Level {dv_level_id:02d} "
                    f"({dv_lv.max_width}×{dv_lv.max_height}@"
                    f"{dv_lv.max_fps:g}fps) requires minimum "
                    f"HEVC {exp_name} (IDC {expected_idc}), "
                    f"but base layer signals {curr_name} "
                    f"(IDC {hevc_level_idc})")
                result["valid"] = False
            elif hevc_level_idc == expected_idc:
                exp_name = f"L{expected_lv.number}" if expected_lv else f"IDC {expected_idc}"
                result["notes"].append({"severity": "pass", "message":
                    f"DV L{dv_level_id:02d} ↔ HEVC {exp_name}: "
                    f"standard IDC mapping confirmed"})

    # --- Bit depth from HEVC constraint flags ---
    si = hevc_decoded.get("stream_info", {})
    depth_str = si.get("bit_depth", "")
    if "≤8-bit" in depth_str and compat.max_depth > 8:
        result["issues"].append(
            f"HEVC constraints limit to 8-bit, but DV {compat.dv_sub} "
            f"expects {compat.max_depth}-bit base layer")
        result["valid"] = False

    # --- QF-4: Monochrome HEVC + DV is always invalid ---
    # All DV profiles require full chroma for tone mapping.
    # IPTPQc2 (Profile 5) needs chroma for the IPT color transform.
    # Profile 8/20 need chroma for YCbCr HDR signal.
    chroma_str = si.get("chroma", "")
    if "Monochrome" in chroma_str:
        result["issues"].append(
            f"HEVC constraints signal monochrome, but DV "
            f"{compat.dv_sub} requires full chroma (4:2:0 minimum) "
            f"for tone mapping and color volume processing")
        result["valid"] = False

    # --- QF-3: Consumer tier warning ---
    # 99% of DV consumer devices (TVs, phones, Shield TV) only
    # support Main Tier. High Tier DV delivery is rare and widely
    # unsupported in consumer hardware.
    hevc_tier = hevc_decoded.get("tier_name", "Main")
    if hevc_tier == "High" and dv_idc in (5, 8, 9, 10, 20):
        result["notes"].append({"severity": "warning", "message":
            f"DV Profile {dv_idc} is intended for consumer delivery. "
            f"High Tier is widely unsupported on consumer DV hardware "
            f"(TVs, streaming devices, phones). "
            f"Main Tier is recommended for DV delivery"})

    # --- Layer structure info ---
    if compat.layer_structure == "BL+EL+RPU":
        if dv_idc == 7:
            result["notes"].append({"severity": "note", "message":
                f"Dual-layer (BL+EL+RPU): 10-bit BL + 2-bit EL → "
                f"12-bit reconstructed. Requires two HEVC decode paths. "
                f"BL alone is valid {compat.fallback_format or 'HDR10'}"})
        else:
            result["notes"].append({"severity": "warning", "message":
                f"DV {compat.dv_sub} is {compat.layer_structure} — "
                f"requires DV-capable decoder"})
    elif compat.fallback_format:
        result["notes"].append({"severity": "note", "message":
            f"Single-layer + RPU: non-DV players decode BL as "
            f"{compat.fallback_format}"})

    # --- EL/INBLD Cross-Validation ──────────────────────────────
    # When a DV profile uses an Enhancement Layer (EL), the HEVC
    # constraint flags MUST set the INBLD (Inter-layer Block-Level
    # Dependency) flag (byte 1, bit 5 = 0x20). This tells the
    # hardware decoder to initiate a dual-pipe decode:
    #   Pipe A: Base Layer (4K HEVC)
    #   Pipe B: Enhancement Layer (usually 1080p residual)
    #   Composer: Merges BL+EL → 12-bit reconstructed output
    #
    # Without INBLD, the decoder displays the BL alone, losing
    # the EL's additional bit depth and causing desynchronization.
    has_el = (compat.layer_structure == "BL+EL+RPU")
    inbld = hevc_decoded.get("constraint_flags", {}).get(
        "general_inbld_flag", 0)
    n_cbytes = hevc_decoded.get("constraint_bytes_present", 0)

    if has_el and not inbld:
        if n_cbytes >= 2:
            # Byte 1 is explicitly present and INBLD is 0 → error
            result["issues"].append(
                f"DV {compat.dv_sub} signals Enhancement Layer "
                f"({compat.layer_structure}), but HEVC constraint "
                f"Byte 1 does not set INBLD flag (0x20). "
                f"This will cause decoder desynchronization — the "
                f"hardware will display the BL alone without "
                f"merging the EL, losing bit-depth reconstruction")
            result["valid"] = False
        else:
            # Byte 1 not present — can't verify INBLD
            result["notes"].append({"severity": "warning", "message":
                f"DV {compat.dv_sub} uses {compat.layer_structure} "
                f"(Enhancement Layer present), but HEVC constraint "
                f"string has only {n_cbytes} byte(s) — cannot verify "
                f"INBLD flag. For strict compliance, Byte 1 should "
                f"include INBLD (0x20) for dual-layer decode"})
    elif has_el and inbld:
        result["notes"].append({"severity": "pass", "message":
            f"INBLD flag set — dual-pipe decode enabled "
            f"for {compat.layer_structure}"})
    elif not has_el and inbld:
        result["notes"].append({"severity": "warning", "message":
            f"INBLD flag is set but DV {compat.dv_sub} is "
            f"single-layer (no EL). INBLD is unnecessary and "
            f"may cause some decoders to stall waiting for a "
            f"non-existent Enhancement Layer"})

    # --- HEVC tier vs DV bitrate cap ---
    hevc_tier = hevc_decoded.get("tier_name", "Main")
    if hevc_lv and dv_lv:
        hevc_max_br = (hevc_lv.max_br_high if hevc_tier == "High"
                       else hevc_lv.max_br_main)
        dv_max_br = (dv_lv.max_br_high if dv_lv.max_br_high > 0
                     else dv_lv.max_br_main)
        if dv_max_br > hevc_max_br:
            result["notes"].append({"severity": "info", "message":
                f"DV L{dv_level_id:02d} allows up to "
                f"{dv_max_br:,} kbps but HEVC {hevc_tier} tier caps at "
                f"{hevc_max_br:,} kbps — HEVC tier is the bottleneck"})

        # --- RPU overhead safety margin (MF-2) ---
        # Dolby Vision adds a Reference Processing Unit (RPU) metadata
        # stream as non-VCL NAL units. This overhead is typically:
        #   Standard RPU:      ~50-150 kbps (static/simple dynamic)
        #   Complex RPU (MEL): ~250 kbps
        #   Enhancement Layer (FEL, Profile 7): much higher
        #
        # If the video essence is encoded near the HEVC level max,
        # the RPU overhead can push the total bitstream over the
        # legal buffer limit, causing strict hardware decoders to
        # drop frames or stutter.
        rpu_margin = 500  # kbps safe margin for RPU overhead
        safe_ceiling = hevc_max_br - rpu_margin
        result["notes"].append({"severity": "info", "message":
            f"RPU overhead: DV metadata adds ~50-250 kbps. "
            f"Safe video bitrate ceiling for HEVC L{hevc_lv.number} "
            f"{hevc_tier} tier: ≤{safe_ceiling:,} kbps "
            f"(level max {hevc_max_br:,} minus ~{rpu_margin} RPU margin)"})
        result["rpu_safe_ceiling_kbps"] = safe_ceiling

    # --- Metadata delivery check ---
    dv_entry = dv_decoded.get("entry", "")
    if dv_entry in compat.entries:
        result["notes"].append({"severity": "note", "message":
            f"Metadata delivery: {METADATA_DELIVERY.get(dv_entry, dv_entry)}"})
    else:
        result["issues"].append(
            f"Entry '{dv_entry}' is not valid for DV Profile {dv_idc}. "
            f"Expected: {', '.join(sorted(compat.entries))}")
        result["valid"] = False

    # --- FF-3: Entry Point Sync ──────────────────────────────────
    # HEVC and DV entry types signal how parameter sets / metadata
    # are delivered in the container:
    #
    # Per MPEG-4 Part 15 and Dolby Vision ISOBMFF spec:
    #   hvc1 = PS out-of-band (in sample entry / config record)
    #   hev1 = PS in-band (in NAL stream)
    #
    # The Dolby wrappers follow a COMPLEMENTARY naming convention:
    #   dvhe = DV wrapper for hvc1 (OOB config — dvCC box carries DV params)
    #   dvh1 = DV wrapper for hev1 (inband — DV params in NAL units)
    #
    # A mismatch means the muxer placed HEVC parameter sets in one
    # location but DV metadata in another. Hardware decoders (LG C4,
    # Apple TV) are extremely sensitive to this — they look for SPS
    # in the location indicated by the entry type. Wrong pairing →
    # decoder fails to initialize the HDR pipeline.
    hevc_entry = hevc_decoded.get("entry", "")
    # Canonical pairings per Dolby ISOBMFF spec
    entry_sync = {
        ("hvc1", "dvhe"): True,   # both out-of-band (config record)
        ("hev1", "dvh1"): True,   # both in-band (NAL stream)
        ("hvc1", "dvh1"): False,  # mismatch: HEVC OOB, DV inband
        ("hev1", "dvhe"): False,  # mismatch: HEVC inband, DV OOB
    }
    pair = (hevc_entry, dv_entry)
    sync_ok = entry_sync.get(pair)

    if sync_ok is True:
        oob = "out-of-band" if hevc_entry == "hvc1" else "in-band"
        result["notes"].append({"severity": "pass", "message":
            f"Entry sync: {hevc_entry}+{dv_entry} — "
            f"both {oob} (consistent delivery)"})
    elif sync_ok is False:
        hevc_mode = ("out-of-band" if hevc_entry == "hvc1"
                     else "in-band")
        dv_mode = ("out-of-band" if dv_entry == "dvhe"
                   else "in-band")
        # Determine correct pairing
        expected_dv = "dvhe" if hevc_entry == "hvc1" else "dvh1"
        result["notes"].append({"severity": "warning", "message":
            f"Entry mismatch: {hevc_entry} ({hevc_mode}) + "
            f"{dv_entry} ({dv_mode}). HEVC and DV parameter delivery "
            f"methods should match. Expected: "
            f"{hevc_entry}+{expected_dv}. Hardware decoders (LG C4, "
            f"Apple TV) may fail to initialize the HDR pipeline"})

    result["notes"].append({"severity": "note", "message": compat.note})

    # --- HLS Brand Cross-Validation (RFC 8216bis §4.4.6.2) ---
    # If the DV decoded result contains HLS brands, validate them
    # against the profile compatibility rules.
    dv_brands = dv_decoded.get("hls_brands", [])
    if dv_brands:
        for bi in dv_brands:
            brand_code = bi["brand"].lower()
            brand_def = HLS_DV_BRANDS.get(brand_code)
            if brand_def:
                # Brand ↔ DV profile match
                if brand_def.dv_profiles and dv_idc not in brand_def.dv_profiles:
                    result["issues"].append(
                        f"HLS brand '{bi['brand']}' ({brand_def.description}) "
                        f"is not valid for DV Profile {dv_idc}. "
                        f"Expected profiles: "
                        f"{', '.join(str(p) for p in sorted(brand_def.dv_profiles))}")
                    result["valid"] = False

                # Brand ↔ HEVC base profile match for DV Profile 8
                if dv_idc == 8 and brand_def.inferred_compat_id is not None:
                    # The brand tells us what fallback format the base layer
                    # should be. Cross-check against HEVC profile:
                    hevc_p = hevc_decoded.get("profile_idc")
                    if hevc_p is not None and hevc_p != 2:
                        # DV Profile 8 always requires HEVC Main 10 (P2)
                        # brand or no brand. But if a brand is present and
                        # the base isn't Main 10, that's extra bad.
                        result["issues"].append(
                            f"HLS brand '{bi['brand']}' implies DV Profile 8 "
                            f"cross-compatibility, but HEVC base layer is "
                            f"Profile {hevc_p} (not Main 10). "
                            f"Profile 8 requires HEVC Main 10 base")
                        result["valid"] = False

                    # Report the brand's role in the binding
                    result["notes"].append({"severity": "info", "message":
                        f"HLS brand '{bi['brand']}': {brand_def.description}. "
                        f"Fallback: strip RPU → "
                        f"{'PQ/HDR10' if brand_def.inferred_compat_id == 1 else ''}"
                        f"{'SDR BT.709' if brand_def.inferred_compat_id == 2 else ''}"
                        f"{'HLG BT.2020' if brand_def.inferred_compat_id == 4 else ''}"
                        f" playback"})
            else:
                # Unknown brand — informational
                result["notes"].append({"severity": "info", "message":
                    f"HLS brand '{bi['brand']}' not in validator's "
                    f"MP4RA brand registry — cannot cross-validate"})

    return result


# =============================================================================
# DOLBY VISION PROFILE RESOLUTION
#
# DV Profile selection is determined by:
#   - Base layer codec (HEVC for dvhe/dvh1, AVC for dvav/dva1, AV1 for dav1)
#   - Transfer function → sub-profile selection
#   - Bit depth
#   - Whether enhancement layer is present (dual-layer vs single+RPU)
#   - User override for legacy profiles
#
# Auto-detection priority for HEVC-based entries (dvhe/dvh1):
#   PQ  + 10-bit + BT.2020/P3 → Profile 8.1 (HDR10-compatible)
#   HLG + 10-bit + BT.2020    → Profile 8.4 (HLG-compatible)
#   SDR + 10-bit + BT.709     → Profile 8.2 (SDR-compatible)
#   User overrides: --dv-profile 5/7 for legacy dual-layer
#
# NON-HEVC profiles (cannot auto-select from hevc entries):
#   Profile 9:  AVC (H.264) — entry dvav/dva1
#   Profile 10: AV1         — entry dav1
#   Profile 20: MV-HEVC     — entry dvh1 (spatial/stereoscopic)
# =============================================================================



# =============================================================================
# AV1 + DOLBY VISION HYBRID CROSS-VALIDATION
#
# DV Profile 10 uses AV1 as base codec (entry "dav1").
# The AV1 base must satisfy:
#   - AV1 Profile 0 (Main), 10-bit, non-monochrome
#   - AV1 level sufficient for the DV level's resolution+fps
#   - Color parameters consistent with DV transfer function
#   - Entry must be dav1 (not dvhe/dvh1 which are HEVC)
# =============================================================================


def validate_av1_hybrid(av1_decoded: dict, dv_decoded: dict) -> dict:
    """
    Cross-validate a decoded AV1 + DV pair.

    Parallel to validate_hybrid() but for AV1-based Dolby Vision
    (DV Profile 10, entry 'dav1').
    """
    dv_display = dv_decoded.get("codec_string_full", dv_decoded["codec_string"])
    result = {
        "valid": True,
        "issues": [],
        "notes": [],
        "compat": None,
        "hybrid_string": f"{av1_decoded['codec_string']}, {dv_display}",
    }

    dv_idc = dv_decoded.get("profile_idc")
    dv_bl_compat = dv_decoded.get("bl_compat_id")

    # Find compatibility rule
    sub_key = _dv_sub_key(dv_idc, dv_bl_compat)
    compat = DV_COMPAT.get(sub_key) or DV_COMPAT.get(str(dv_idc))

    if not compat:
        result["issues"].append(
            f"No compatibility rule for DV profile {dv_idc} — "
            f"cannot validate base layer")
        result["valid"] = False
        return result

    result["compat"] = compat

    # ── CHECK A1: Base codec match ──────────────────────────────────
    # DV Profile 10 requires AV1 base. Any other DV profile on AV1 is wrong.
    if compat.base_codec != "AV1":
        result["issues"].append(
            f"DV Profile {dv_idc} uses {compat.base_codec} base layer, "
            f"not AV1. Cannot pair with av01 base. "
            f"Expected entry: {', '.join(sorted(compat.entries))}")
        result["valid"] = False
        return result

    result["notes"].append({"severity": "pass", "message":
        f"DV Profile {dv_idc} correctly uses AV1 base layer"})

    # ── CHECK A2: AV1 profile contract ──────────────────────────────
    # DV P10 requires AV1 Profile 0 (Main), 10-bit, non-monochrome
    av1_profile = av1_decoded.get("seq_profile")
    av1_depth = av1_decoded.get("bit_depth")
    av1_mono = av1_decoded.get("monochrome", 0)

    if av1_profile is not None and av1_profile != 0:
        result["issues"].append(
            f"DV Profile 10 requires AV1 Profile 0 (Main), "
            f"got Profile {av1_profile} ({av1_decoded.get('profile_name', '?')})")
        result["valid"] = False
    else:
        result["notes"].append({"severity": "pass", "message":
            f"AV1 Profile {av1_profile} (Main) matches DV Profile 10 requirement"})

    if av1_depth is not None and av1_depth != 10:
        result["issues"].append(
            f"DV Profile 10 requires 10-bit AV1 base layer, "
            f"got {av1_depth}-bit")
        result["valid"] = False
    else:
        result["notes"].append({"severity": "pass", "message":
            f"AV1 bit depth: {av1_depth}-bit (correct for DV P10)"})

    if av1_mono:
        result["issues"].append(
            "DV Profile 10 requires full chroma (non-monochrome) "
            "AV1 base for tone mapping and color volume processing")
        result["valid"] = False

    # ── CHECK A3: AV1 level headroom ────────────────────────────────
    dv_level_id = dv_decoded.get("level_id", 0)
    av1_level_idx = av1_decoded.get("seq_level_idx")
    dv_lv = DV_LEVEL_LOOKUP.get(dv_level_id)

    if dv_lv and av1_level_idx is not None:
        expected_idx = DV_TO_AV1_LEVEL_IDX.get(dv_level_id)
        av1_lv = AV1_LEVEL_LOOKUP.get(av1_level_idx)

        if expected_idx is not None:
            expected_lv = AV1_LEVEL_LOOKUP.get(expected_idx)
            if av1_level_idx < expected_idx:
                exp_name = expected_lv.name if expected_lv else f"idx {expected_idx}"
                curr_name = av1_lv.name if av1_lv else f"idx {av1_level_idx}"
                result["issues"].append(
                    f"DV Level {dv_level_id:02d} "
                    f"({dv_lv.max_width}×{dv_lv.max_height}@"
                    f"{dv_lv.max_fps:g}fps) requires minimum "
                    f"AV1 Level {exp_name} (idx {expected_idx}), "
                    f"but base layer signals Level {curr_name} "
                    f"(idx {av1_level_idx})")
                result["valid"] = False
            elif av1_level_idx == expected_idx:
                exp_name = expected_lv.name if expected_lv else f"idx {expected_idx}"
                result["notes"].append({"severity": "pass", "message":
                    f"DV L{dv_level_id:02d} ↔ AV1 L{exp_name}: "
                    f"standard level mapping confirmed"})
            else:
                # Higher AV1 level than minimum — report headroom
                exp_name = expected_lv.name if expected_lv else f"idx {expected_idx}"
                curr_name = av1_lv.name if av1_lv else f"idx {av1_level_idx}"
                result["notes"].append({"severity": "pass", "message":
                    f"AV1 Level {curr_name} exceeds DV L{dv_level_id:02d} "
                    f"minimum (AV1 L{exp_name}) — headroom available"})

    # ── CHECK A4: Color consistency ─────────────────────────────────
    if av1_decoded.get("has_optional_fields"):
        tc = av1_decoded.get("transfer_characteristics", 1)
        dv_brands = dv_decoded.get("hls_brands", [])

        # Check against brand expectations
        for bi in dv_brands:
            brand_code = bi.get("brand", "").lower()
            brand_def = HLS_DV_BRANDS.get(brand_code)
            if brand_def and brand_def.video_range:
                if brand_def.video_range == "HLG" and tc != 18:
                    result["notes"].append({"severity": "warning", "message":
                        f"HLS brand '{brand_code}' implies HLG content, "
                        f"but AV1 transfer_characteristics={tc} "
                        f"(expected 18 for HLG)"})
                elif brand_def.video_range == "PQ" and tc != 16:
                    result["notes"].append({"severity": "warning", "message":
                        f"HLS brand '{brand_code}' implies PQ content, "
                        f"but AV1 transfer_characteristics={tc} "
                        f"(expected 16 for PQ)"})
                elif brand_def.video_range == "SDR" and tc not in (1, 6, 13):
                    result["notes"].append({"severity": "warning", "message":
                        f"HLS brand '{brand_code}' implies SDR content, "
                        f"but AV1 transfer_characteristics={tc} "
                        f"(expected 1/6/13 for SDR)"})

    # ── CHECK A5: Brand ↔ profile validation ────────────────────────
    dv_brands = dv_decoded.get("hls_brands", [])
    if dv_brands:
        for bi in dv_brands:
            brand_code = bi.get("brand", "").lower()
            brand_def = HLS_DV_BRANDS.get(brand_code)
            if brand_def:
                if brand_def.dv_profiles and dv_idc not in brand_def.dv_profiles:
                    result["issues"].append(
                        f"HLS brand '{brand_code}' ({brand_def.description}) "
                        f"is not valid for DV Profile {dv_idc}. "
                        f"Expected profiles: "
                        f"{', '.join(str(p) for p in sorted(brand_def.dv_profiles))}")
                    result["valid"] = False
                else:
                    result["notes"].append({"severity": "info", "message":
                        f"HLS brand '{brand_code}': {brand_def.description}"})

    # ── CHECK A6: Entry sync ────────────────────────────────────────
    dv_entry = dv_decoded.get("entry", "")
    if dv_entry != "dav1":
        result["issues"].append(
            f"AV1 base layer requires DV entry 'dav1', got '{dv_entry}'. "
            f"(dvh1/dvhe are HEVC entries, not AV1)")
        result["valid"] = False
    else:
        result["notes"].append({"severity": "pass", "message":
            f"Entry sync: av01+dav1 — both AV1-based (correct)"})
        result["notes"].append({"severity": "note", "message":
            "Metadata delivery: out-of-band (sample description)"})

    # ── CHECK A7: Tier bitrate ──────────────────────────────────────
    av1_tier = av1_decoded.get("tier", 0)
    av1_lv = AV1_LEVEL_LOOKUP.get(av1_level_idx) if av1_level_idx else None
    if av1_lv and dv_lv:
        from .av1.profiles import BITRATE_PROFILE_FACTOR
        bpf = BITRATE_PROFILE_FACTOR.get(av1_profile or 0, 1.0)
        av1_max_br_mbps = ((av1_lv.high_mbps if av1_tier == 1 and av1_lv.high_mbps
                           else av1_lv.main_mbps) * bpf)
        dv_max_br_kbps = (dv_lv.max_br_high if dv_lv.max_br_high > 0
                          else dv_lv.max_br_main)
        dv_max_br_mbps = dv_max_br_kbps / 1000.0

        if dv_max_br_mbps > av1_max_br_mbps:
            result["notes"].append({"severity": "info", "message":
                f"DV L{dv_level_id:02d} allows up to "
                f"{dv_max_br_mbps:.1f} Mbps but AV1 "
                f"{'Main' if av1_tier == 0 else 'High'} tier caps at "
                f"{av1_max_br_mbps:.1f} Mbps — AV1 tier is the bottleneck"})

        # RPU overhead margin
        rpu_margin_mbps = 0.5
        safe_ceiling = av1_max_br_mbps - rpu_margin_mbps
        result["notes"].append({"severity": "info", "message":
            f"RPU overhead: DV metadata adds ~0.05-0.25 Mbps. "
            f"Safe video bitrate ceiling: ≤{safe_ceiling:.1f} Mbps "
            f"(AV1 cap {av1_max_br_mbps:.1f} minus ~{rpu_margin_mbps} RPU margin)"})
        result["rpu_safe_ceiling_mbps"] = safe_ceiling

    # Layer structure info
    if compat.fallback_format:
        result["notes"].append({"severity": "note", "message":
            f"Single-layer + RPU: non-DV players decode BL as "
            f"{compat.fallback_format}"})

    result["notes"].append({"severity": "note", "message": compat.note})

    return result



def decode_codec_string(codec_string: str) -> dict:
    """Auto-detect codec family and decode."""
    s = codec_string.strip()
    # Strip brand suffix before identifying entry
    base = s.split("/")[0] if "/" in s else s
    entry = base.split(".")[0].lower()

    info = CODEC_ENTRIES.get(entry)
    if not info:
        raise ValueError(
            f"Cannot identify codec family from entry '{entry}'. "
            f"Expected: {', '.join(sorted(CODEC_ENTRIES.keys()))}")

    family = info["family"]
    if family == "hevc":
        return decode_hevc(s)
    elif family == "av1":
        return decode_av1(s)
    elif family == "vp9":
        return decode_vp9(s)
    elif family == "dv":
        return decode_dv(s)


def decode_hybrid_string(hybrid_string: str) -> dict:
    """
    Decode an HLS-style hybrid codec string like:
      "hvc1.2.4.L153.B0, dvh1.08.06"        (HEVC + DV)
      "av01.0.13M.10, dav1.10.06"            (AV1 + DV)
      "av01.0.13M.10, dav1.10.06/db4h"       (AV1 + DV + brand)

    Parses both components, cross-validates them, and returns a combined
    result with compatibility analysis.

    Returns dict with:
      base: decoded HEVC or AV1 dict (also aliased as 'hevc' or 'av1')
      dv: decoded DV dict
      validation: validate_hybrid() or validate_av1_hybrid() result
    """
    # Split on comma — standard HLS codecs= separator
    parts = [p.strip() for p in hybrid_string.split(",")]

    hevc_part = None
    av1_part = None
    dv_part = None

    for p in parts:
        base = p.split("/")[0] if "/" in p else p
        entry = base.split(".")[0].lower()
        info = CODEC_ENTRIES.get(entry)
        if not info:
            raise ValueError(f"Unknown entry '{entry}' in hybrid string")
        family = info["family"]
        if family == "hevc":
            if hevc_part:
                raise ValueError(f"Multiple HEVC entries: '{hevc_part}' and '{p}'")
            hevc_part = p
        elif family == "av1":
            if av1_part:
                raise ValueError(f"Multiple AV1 entries: '{av1_part}' and '{p}'")
            av1_part = p
        elif family == "dv":
            if dv_part:
                raise ValueError(f"Multiple DV entries: '{dv_part}' and '{p}'")
            dv_part = p

    if not dv_part:
        raise ValueError(
            f"Hybrid string requires a DV component. Got: '{hybrid_string}'")

    if hevc_part and av1_part:
        raise ValueError(
            f"Hybrid string cannot have both HEVC and AV1 base layers. "
            f"Got: '{hevc_part}' and '{av1_part}'")

    if not hevc_part and not av1_part:
        raise ValueError(
            f"Hybrid string requires a base layer (HEVC or AV1). "
            f"Got: '{hybrid_string}'")

    dv_decoded = decode_dv(dv_part)

    if av1_part:
        av1_decoded = decode_av1(av1_part)
        validation = validate_av1_hybrid(av1_decoded, dv_decoded)
        return {
            "av1": av1_decoded,
            "base": av1_decoded,
            "dv": dv_decoded,
            "validation": validation,
        }
    else:
        hevc_decoded = decode_hevc(hevc_part)
        validation = validate_hybrid(hevc_decoded, dv_decoded)
        return {
            "hevc": hevc_decoded,
            "base": hevc_decoded,
            "dv": dv_decoded,
            "validation": validation,
        }


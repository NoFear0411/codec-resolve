"""
Master codec string resolver: Content descriptor → codec string(s).

Bidirectional with the decode path. Given content parameters (resolution,
framerate, bit depth, etc.), computes the spec-correct codec string.
"""
from typing import List
from .models import Content, Chroma, Transfer, Gamut, Scan, Tier, ConstraintStyle, ResolvedCodec
from .models import TRANSFER_TO_TC, GAMUT_TO_CP, GAMUT_TO_MC
from .hevc.levels import resolve_hevc_level, resolve_hevc_tier
from .hevc.profiles import resolve_hevc_profile, format_hevc_string, HEVCProfile, HEVC_PROFILE_DEFS
from .dv.levels import resolve_dv_level
from .dv.profiles import resolve_dv_profile, format_dv_string, DV_COMPAT, _dv_sub_key, METADATA_DELIVERY
from .av1.levels import resolve_av1_level, resolve_av1_tier
from .av1.profiles import (
    resolve_av1_profile, format_av1_string, AV1_PROFILE_DEFS,
    BITRATE_PROFILE_FACTOR, SUBSAMPLING_FROM_CHROMA,
)


def resolve(content: Content, codecs: List[str]) -> List[ResolvedCodec]:
    """
    Master resolver: given content + requested codecs, return resolved strings.
    """
    content.validate()
    results = []

    for codec in codecs:
        if codec in ("hvc1", "hev1"):
            results.append(_resolve_hevc(content, codec))
        elif codec in ("dvhe", "dvh1", "dvav", "dva1", "dav1"):
            results.append(_resolve_dv(content, codec))
        elif codec == "av01":
            results.append(_resolve_av1(content, codec))
        else:
            raise ValueError(f"Unknown codec entry: '{codec}'. "
                             f"Use: hvc1, hev1, av01, dvhe, dvh1, dvav, dva1, dav1")
    return results


def _resolve_hevc(c: Content, entry: str) -> ResolvedCodec:
    """Resolve a single HEVC codec string."""
    profile = resolve_hevc_profile(c)
    level = resolve_hevc_level(c)
    tier = resolve_hevc_tier(c, level)
    codec_str = format_hevc_string(entry, profile, tier, level)

    notes = []
    if tier == 1:
        notes.append("High tier selected (bitrate exceeds Main tier)")
    if profile.idc in (4, 12, 13):
        notes.append(f"RExt sub-profile: {profile.name}")
    elif profile.idc in (5, 11):
        pdef = HEVC_PROFILE_DEFS[profile.idc]
        notes.append(f"{pdef.note}")
    elif profile.idc in (3, 6, 7, 8, 9, 10):
        pdef = HEVC_PROFILE_DEFS[profile.idc]
        notes.append(f"{pdef.note}")
    if c.constraint_style == ConstraintStyle.MINIMAL:
        notes.append("Constraint bytes: minimal (matches x265/FFmpeg)")
    else:
        notes.append("Constraint bytes: full (all truthful flags asserted)")
    if entry == "hev1":
        notes.append("hev1: parameter sets in band (each sample)")
    elif entry == "hvc1":
        notes.append("hvc1: parameter sets out of band (sample entry)")

    return ResolvedCodec(
        codec_string=codec_str,
        entry=entry,
        family="hevc",
        profile_name=f"HEVC {profile.name} (profile {profile.idc})",
        level_name=f"Level {level.number} (level_idc={level.idc})",
        tier_name="High" if tier == 1 else "Main",
        notes=notes,
    )


def _resolve_dv(c: Content, entry: str) -> ResolvedCodec:
    """Resolve a single Dolby Vision codec string."""
    # DV requires 4:2:0 for all profiles
    if c.chroma != Chroma.YUV420:
        raise ValueError(
            f"Dolby Vision ({entry}) requires 4:2:0 chroma subsampling, "
            f"got {c.chroma}. DV does not support 4:2:2 or 4:4:4.")

    profile = resolve_dv_profile(c)
    level = resolve_dv_level(c)

    # Validate entry vs profile base codec
    compat = DV_COMPAT.get(_dv_sub_key(profile.idc, profile.bl_compat_id))
    if not compat:
        compat = DV_COMPAT.get(str(profile.idc))

    if compat:
        if entry not in compat.entries:
            raise ValueError(
                f"DV Profile {profile.idc} requires entry "
                f"{'/'.join(sorted(compat.entries))}, "
                f"but got '{entry}'. "
                f"Base codec: {compat.base_codec}")

    # Validate level is within profile's supported range
    max_levels = {5: 13, 7: 9, 8: 13, 9: 9, 20: 13}
    max_lv = max_levels.get(profile.idc, 13)
    if level.id > max_lv:
        raise ValueError(
            f"DV Profile {profile.idc} only supports up to Level {max_lv}, "
            f"but content requires Level {level.id}.")

    codec_str = format_dv_string(entry, profile, level)

    notes = []

    # Profile-specific notes
    if profile.idc == 5:
        notes.append("⚠ IPTPQc2 closed-loop: NO standard fallback. "
                      "Requires DV-capable decoder")
        notes.append("Colorspace: IPTPQc2 (proprietary, not standard YCbCr)")
    elif profile.idc == 7:
        notes.append("Dual-layer (BL+EL+RPU): 10-bit BL + 2-bit EL → 12-bit")
        notes.append("BL alone = valid HDR10 (hardware fallback)")
        notes.append("Full DV requires two simultaneous HEVC decode paths")
    elif profile.idc == 8:
        # Signaled fallback via bl_signal_compatibility_id
        fallback_map = {
            1: ("HDR10", "signaled", "BL is standard PQ/BT.2020 YCbCr"),
            2: ("SDR",   "signaled", "BL is standard SDR/BT.709 YCbCr"),
            4: ("HLG",   "signaled", "BL is standard HLG/BT.2020 YCbCr"),
        }
        fb = fallback_map.get(profile.bl_compat_id)
        if fb:
            notes.append(f"BL compatible with {fb[0]} "
                         f"(strip RPU → valid {fb[0]})")
            notes.append(f"Fallback: {fb[1]} ({fb[2]})")
    elif profile.idc == 9:
        notes.append("AVC (H.264) base — 8-bit SDR legacy fallback")
    elif profile.idc == 10:
        notes.append("AV1 base — NOT HEVC. Entry must be 'dav1'")
    elif profile.idc == 20:
        notes.append("MV-HEVC spatial (stereoscopic L/R views)")
        notes.append("Fallback: single-eye 2D HEVC Main 10")

    # Metadata delivery
    notes.append(f"{entry}: RPU {METADATA_DELIVERY.get(entry, entry)}")

    return ResolvedCodec(
        codec_string=codec_str,
        entry=entry,
        family="dv",
        profile_name=profile.name,
        level_name=f"DV Level {level.id:02d} "
                   f"(≤{level.max_width}×{level.max_height}@{level.max_fps:g}fps)",
        notes=notes,
    )


def _resolve_av1(c: Content, entry: str) -> ResolvedCodec:
    """Resolve a single AV1 codec string (always full 10-field form)."""
    profile_idx = resolve_av1_profile(c)
    level = resolve_av1_level(c)
    tier = resolve_av1_tier(c, level)

    # Monochrome flag
    monochrome = 1 if c.chroma == Chroma.MONO else 0

    # Chroma subsampling
    sub_x, sub_y = SUBSAMPLING_FROM_CHROMA.get(c.chroma, (1, 1))
    chroma_sample_position = 0  # Unknown (CSP_UNKNOWN) — safe default

    # Color parameters from Content enums → H.273 codes
    cp = GAMUT_TO_CP.get(c.gamut, 1)
    tc = TRANSFER_TO_TC.get(c.transfer, 1)
    mc = GAMUT_TO_MC.get(c.gamut, 1)

    # Full range flag: 0 = limited (studio swing), 1 = full (PC)
    video_full_range_flag = 0

    codec_str = format_av1_string(
        profile=profile_idx, level_idx=level.seq_level_idx, tier=tier,
        bit_depth=c.bit_depth, monochrome=monochrome,
        subsampling_x=sub_x, subsampling_y=sub_y,
        chroma_sample_position=chroma_sample_position,
        color_primaries=cp, transfer_characteristics=tc,
        matrix_coefficients=mc, video_full_range_flag=video_full_range_flag,
    )

    pdef = AV1_PROFILE_DEFS[profile_idx]
    bpf = BITRATE_PROFILE_FACTOR[profile_idx]
    cap_mbps = (level.high_mbps if tier == 1 and level.high_mbps
                else level.main_mbps) * bpf

    notes = []
    if tier == 1:
        notes.append("High tier selected (bitrate exceeds Main tier)")
    notes.append(f"Effective max bitrate: {cap_mbps:.1f} Mbps "
                 f"({'Main' if tier == 0 else 'High'} tier × P{profile_idx} "
                 f"factor {bpf}×)")
    if profile_idx == 0:
        notes.append("AV1 Main — standard consumer profile (streaming/browsers)")
    elif profile_idx == 1:
        notes.append("AV1 High — 4:4:4 content (no monochrome)")
    elif profile_idx == 2:
        notes.append("AV1 Professional — 12-bit / 4:2:2 / broadcast mastering")

    return ResolvedCodec(
        codec_string=codec_str,
        entry=entry,
        family="av1",
        profile_name=f"AV1 {pdef.name} (profile {profile_idx})",
        level_name=f"Level {level.name} (seq_level_idx={level.seq_level_idx})",
        tier_name="High" if tier == 1 else "Main",
        notes=notes,
    )


# =============================================================================
# DISPLAY
# =============================================================================


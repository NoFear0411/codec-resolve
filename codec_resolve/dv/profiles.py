"""
Dolby Vision profile definitions, compatibility contracts, and profile resolution.

Source: ETSI TS 103 572, Dolby ISOBMFF Spec.
"""
from dataclasses import dataclass
from typing import Dict, Optional
from ..models import Content, Chroma, Transfer, Gamut
from .levels import DVLevel


@dataclass
class DVCompat:
    """Defines the base layer contract for a Dolby Vision profile."""
    dv_profile: int
    dv_sub: str                      # "8.1", "8.2", "8.4", "5", "7", "9", "10", "20"
    base_codec: str                  # "HEVC", "AVC", "AV1", "MV-HEVC"
    hevc_profiles: set               # Required HEVC profile_idc set (empty for non-HEVC)
    base_label: str                  # Human-readable base requirement
    max_depth: int                   # Max BL bit depth
    chroma: str                      # Required chroma
    transfer: Optional[str]          # Expected BL transfer (None = any/proprietary)
    colorspace: str                  # "YCbCr" or "IPTPQc2" (proprietary)
    layer_structure: str             # "BL+RPU", "BL+EL+RPU", "BL+RPU (proprietary)"
    fallback_type: Optional[str]     # "hardware" (strip RPU), "signaled" (compat ID), None
    fallback_format: Optional[str]   # What non-DV players see (None = no fallback)
    entries: set                     # Valid codec string entries {"dvhe","dvh1","dav1",etc}
    status: str                      # "Current", "Legacy", "Deprecated", etc.
    note: str


DV_COMPAT = {
    # ── Profile 5: Proprietary HEVC (IPTPQc2 closed-loop) ──
    # Luma = I, Chroma = P and T. Reshaping metadata maps IPTPQc2 → YCbCr.
    # Playing as standard Main 10 produces green/purple color distortion.
    # REQUIRES HEVC Profile 2 (Main 10) — IPT color transform needs 10-bit.
    "5": DVCompat(
        dv_profile=5, dv_sub="5",
        base_codec="HEVC", hevc_profiles={2},
        base_label="HEVC Main 10 (IPTPQc2 colorspace)",
        max_depth=10, chroma="4:2:0", transfer=None,
        colorspace="IPTPQc2",
        layer_structure="BL+EL+RPU",
        fallback_type=None, fallback_format=None,
        entries={"dvhe", "dvc1", "dvhp"},
        status="Legacy (phased out by streaming services)",
        note="Closed-loop system: IPTPQc2 colorspace requires DV decoder. "
             "No standard HDR/SDR fallback. Colors will appear green/purple "
             "if decoded as standard HEVC Main 10"),

    # ── Profile 7: HEVC Dual-Layer (BL+EL+RPU, Blu-ray) ──
    # BL is valid Main 10 PQ, but full DV reconstructs 12-bit from
    # 10-bit BL + 2-bit EL. Used in UHD Blu-ray.
    "7": DVCompat(
        dv_profile=7, dv_sub="7",
        base_codec="HEVC", hevc_profiles={2},
        base_label="HEVC Main 10 (BL) + HEVC EL",
        max_depth=12, chroma="4:2:0", transfer="pq",
        colorspace="YCbCr",
        layer_structure="BL+EL+RPU",
        fallback_type="hardware",
        fallback_format="HDR10 (PQ + BT.2020) — BL only, 10-bit",
        entries={"dvhe", "dvh1"},
        status="Current (UHD Blu-ray)",
        note="Dual-layer: 10-bit BL + 2-bit EL → 12-bit reconstructed. "
             "BL alone is valid HDR10 if EL is stripped. "
             "Requires two simultaneous HEVC decode paths for full DV"),

    # ── Profile 8.1: HEVC Single-Layer HDR10-Compatible ──
    "8.1": DVCompat(
        dv_profile=8, dv_sub="8.1",
        base_codec="HEVC", hevc_profiles={2},
        base_label="HEVC Main 10",
        max_depth=10, chroma="4:2:0", transfer="pq",
        colorspace="YCbCr",
        layer_structure="BL+RPU",
        fallback_type="signaled",
        fallback_format="HDR10 (PQ + BT.2020)",
        entries={"dvhe", "dvh1"},
        status="Current ★ (dominant streaming profile)",
        note="bl_signal_compatibility_id=1: BL is valid HDR10. "
             "Strip RPU → standard PQ/BT.2020 10-bit playback"),

    # ── Profile 8.2: HEVC Single-Layer SDR-Compatible ──
    "8.2": DVCompat(
        dv_profile=8, dv_sub="8.2",
        base_codec="HEVC", hevc_profiles={2},
        base_label="HEVC Main 10",
        max_depth=10, chroma="4:2:0", transfer="sdr",
        colorspace="YCbCr",
        layer_structure="BL+RPU",
        fallback_type="signaled",
        fallback_format="SDR (BT.709)",
        entries={"dvhe", "dvh1"},
        status="Current",
        note="bl_signal_compatibility_id=2: BL is valid SDR BT.709. "
             "Strip RPU → standard SDR playback"),

    # ── Profile 8.4: HEVC Single-Layer HLG-Compatible ──
    "8.4": DVCompat(
        dv_profile=8, dv_sub="8.4",
        base_codec="HEVC", hevc_profiles={2},
        base_label="HEVC Main 10",
        max_depth=10, chroma="4:2:0", transfer="hlg",
        colorspace="YCbCr",
        layer_structure="BL+RPU",
        fallback_type="signaled",
        fallback_format="HLG (BT.2020)",
        entries={"dvhe", "dvh1"},
        status="Current (Apple / broadcast)",
        note="bl_signal_compatibility_id=4: BL is valid HLG BT.2020. "
             "Strip RPU → standard HLG playback. Used by Apple content"),

    # ── Profile 8 (generic): HEVC Single-Layer, no standard fallback ──
    # bl_signal_compatibility_id=0: the RPU does not signal a standard
    # fallback mode. Non-DV players can still decode the HEVC base layer,
    # but the result depends on the actual content (may be valid PQ/HLG/SDR
    # but the RPU doesn't declare it). Used with --compat none.
    "8": DVCompat(
        dv_profile=8, dv_sub="8",
        base_codec="HEVC", hevc_profiles={2},
        base_label="HEVC Main 10",
        max_depth=10, chroma="4:2:0", transfer=None,
        colorspace="YCbCr",
        layer_structure="BL+RPU",
        fallback_type=None,
        fallback_format=None,
        entries={"dvhe", "dvh1"},
        status="Current (no-fallback variant)",
        note="bl_signal_compatibility_id=0: RPU does not declare a standard "
             "fallback mode. Non-DV players decode BL as raw HEVC Main 10 "
             "without guaranteed format signaling"),

    # ── Profile 9: AVC Single-Layer + RPU (legacy compatibility) ──
    "9": DVCompat(
        dv_profile=9, dv_sub="9",
        base_codec="AVC", hevc_profiles=set(),
        base_label="AVC (H.264) High Profile",
        max_depth=8, chroma="4:2:0", transfer="sdr",
        colorspace="YCbCr",
        layer_structure="BL+RPU",
        fallback_type="hardware",
        fallback_format="SDR (8-bit AVC)",
        entries={"dvav", "dva1"},
        status="Current (AVC legacy devices)",
        note="8-bit AVC base with DV RPU metadata. Allows DV tone-mapping "
             "on an 8-bit SDR AVC stream for older H.264-only devices"),

    # ── Profile 10: AV1 Single-Layer + RPU ──
    "10": DVCompat(
        dv_profile=10, dv_sub="10",
        base_codec="AV1", hevc_profiles=set(),
        base_label="AV1 Main 10",
        max_depth=10, chroma="4:2:0", transfer="pq",
        colorspace="YCbCr",
        layer_structure="BL+RPU",
        fallback_type="signaled",
        fallback_format="HDR10 (AV1 PQ)",
        entries={"dav1"},
        status="Current (royalty-free streaming)",
        note="AV1-based DV. NOT HEVC. Entry is 'dav1'. "
             "Used by Netflix, YouTube, and other AV1-adopting services"),

    # ── Profile 20: MV-HEVC Spatial/3D (Vision Pro) ──
    "20": DVCompat(
        dv_profile=20, dv_sub="20",
        base_codec="MV-HEVC", hevc_profiles=set(),
        base_label="MV-HEVC (Multiview HEVC)",
        max_depth=10, chroma="4:2:0", transfer="pq",
        colorspace="YCbCr",
        layer_structure="BL+RPU (multiview)",
        fallback_type="hardware",
        fallback_format="2D HEVC Main 10 (single-eye view)",
        entries={"dvh1"},
        status="Current ★ (Apple Vision Pro / spatial video)",
        note="Stereoscopic 3D: decodes two 4K 10-bit views (L/R) "
             "simultaneously. Fallback is single-eye 2D HEVC Main 10. "
             "Requires MV-HEVC decoder capability"),
}



METADATA_DELIVERY = {
    "dvh1": "out-of-band (sample description — HLS/MP4)",
    "dvhe": "in-band (NAL units — DASH/TS)",
    "dva1": "out-of-band (sample description — HLS/MP4)",
    "dvav": "in-band (NAL units)",
    "dav1": "out-of-band (sample description)",
    # Non-standard entries
    "dvc1": "deprecated pre-standard container (delivery unknown)",
    "dvhp": "OMAF/VR container (ISO/IEC 23090-2)",
}


def _dv_sub_key(dv_profile_idc: int, bl_compat_id=None) -> str:
    """Map DV profile + bl_compat_id to compatibility lookup key.

    For Profile 8, the sub-profile is determined by bl_signal_compatibility_id:
      1 → "8.1" (HDR10-compatible)
      2 → "8.2" (SDR-compatible)
      4 → "8.4" (HLG-compatible)
      0 → "8"   (no standard fallback declared)
      None → "8.1" (unknown from codec string — default to most common)
    """
    if dv_profile_idc == 8:
        if bl_compat_id is None:
            return "8.1"  # Unknown: default to most common sub-profile
        mapping = {0: "8", 1: "8.1", 2: "8.2", 4: "8.4"}
        return mapping.get(bl_compat_id, "8.1")
    return str(dv_profile_idc)


@dataclass
class DVProfile:
    """Resolved Dolby Vision profile."""
    idc: int
    name: str
    bl_compat_id: int = 0   # For Profile 8: identifies the BL compatibility
    #   bl_compat_id=1: HDR10 (PQ + BT.2020/P3)
    #   bl_compat_id=2: SDR (BT.709)
    #   bl_compat_id=4: HLG (BT.2020)


def resolve_dv_profile(c: Content) -> DVProfile:
    """
    Select the correct DV profile from content parameters.

    Priority:
      1. --dv-profile (explicit profile override)
      2. --compat / --dv-bl-compat (explicit compatibility, auto Profile 8)
      3. Transfer function inference (PQ→8.1, HLG→8.4, SDR→8.2)

    Profile 9 (AVC), 10 (AV1), 20 (MV-HEVC) are NOT auto-selected
    from HEVC entries — they require explicit --dv-profile override.

    Returns the profile with the correct bl_compat_id for Profile 8 variants.
    """
    # 1. User explicitly requested a profile number
    if c.dv_profile is not None:
        return _resolve_explicit_dv_profile(c)

    # 2. User explicitly specified compatibility mode (--compat / --dv-bl-compat)
    if c.dv_bl_compat_id is not None:
        compat_names = {
            0: ("DV Profile 8 (no standard fallback)", 0),
            1: ("DV Profile 8.1 (HDR10-Compat)", 1),
            2: ("DV Profile 8.2 (SDR-Compat)", 2),
            4: ("DV Profile 8.4 (HLG-Compat)", 4),
        }
        name, cid = compat_names.get(c.dv_bl_compat_id,
                                     (f"DV Profile 8 (bl_compat={c.dv_bl_compat_id})",
                                      c.dv_bl_compat_id))
        return DVProfile(8, name, bl_compat_id=cid)

    # 3. Auto-detect from transfer: prefer Profile 8.x (single-layer + RPU)
    if c.transfer == Transfer.PQ and c.bit_depth >= 10:
        return DVProfile(8, "DV Profile 8.1 (HDR10-Compat)", bl_compat_id=1)

    elif c.transfer == Transfer.HLG and c.bit_depth >= 10:
        return DVProfile(8, "DV Profile 8.4 (HLG-Compat)", bl_compat_id=4)

    elif c.transfer == Transfer.SDR:
        if c.bit_depth >= 10:
            return DVProfile(8, "DV Profile 8.2 (SDR-Compat)", bl_compat_id=2)
        # 8-bit SDR: still Profile 8.2 — the BL is Main 10 container
        # even if content is 8-bit (10-bit container is standard for DV)
        return DVProfile(8, "DV Profile 8.2 (SDR-Compat)", bl_compat_id=2)

    raise ValueError(
        f"Cannot auto-detect DV profile for {c.bit_depth}-bit "
        f"{c.transfer.value}/{c.gamut.value}. "
        f"Use --dv-profile or --compat to specify explicitly.")


def _resolve_explicit_dv_profile(c: Content) -> DVProfile:
    """Handle user-specified --dv-profile."""
    dp = c.dv_profile

    if dp == 5:
        if c.bit_depth < 10:
            raise ValueError("DV Profile 5 requires 10-bit")
        return DVProfile(5, "DV Profile 5 (HEVC IPTPQc2 Closed-Loop)",
                         bl_compat_id=0)

    elif dp == 7:
        if c.bit_depth < 10:
            raise ValueError("DV Profile 7 requires ≥10-bit")
        if c.transfer != Transfer.PQ:
            raise ValueError("DV Profile 7 requires PQ transfer")
        return DVProfile(7, "DV Profile 7 (HEVC Dual-Layer BL+EL)",
                         bl_compat_id=0)

    elif dp == 8:
        # Auto-detect sub-profile from transfer, or use explicit bl_compat_id
        if c.dv_bl_compat_id is not None:
            names = {1: "HDR10-Compat", 2: "SDR-Compat", 4: "HLG-Compat"}
            n = names.get(c.dv_bl_compat_id, f"bl_compat={c.dv_bl_compat_id}")
            return DVProfile(8, f"DV Profile 8 ({n})",
                             bl_compat_id=c.dv_bl_compat_id)
        # Infer from transfer
        if c.transfer == Transfer.PQ:
            return DVProfile(8, "DV Profile 8.1 (HDR10-Compat)", bl_compat_id=1)
        elif c.transfer == Transfer.HLG:
            return DVProfile(8, "DV Profile 8.4 (HLG-Compat)", bl_compat_id=4)
        elif c.transfer == Transfer.SDR:
            return DVProfile(8, "DV Profile 8.2 (SDR-Compat)", bl_compat_id=2)

    elif dp == 9:
        # AVC profile — warn that this doesn't pair with HEVC entries
        return DVProfile(9, "DV Profile 9 (AVC + RPU)", bl_compat_id=0)

    elif dp == 10:
        # AV1 profile — NOT HEVC
        return DVProfile(10, "DV Profile 10 (AV1 + RPU)", bl_compat_id=0)

    elif dp == 20:
        if c.bit_depth < 10:
            raise ValueError("DV Profile 20 requires 10-bit")
        return DVProfile(20, "DV Profile 20 (MV-HEVC Spatial)",
                         bl_compat_id=0)

    raise ValueError(
        f"Unknown/unsupported DV profile: {dp}. "
        f"Valid: 5, 7, 8, 9, 10, 20.")


# =============================================================================
# DOLBY VISION CODEC STRING FORMATTING
#
# Format: <entry>.<profile_idc:02d>.<level_id:02d>
#
# That's it. No bitmasks, no constraint bytes, no tier flags.
#
# Valid entries (determine base codec + metadata delivery):
#   HEVC:  dvhe (in-band/DASH), dvh1 (out-of-band/HLS)
#   AVC:   dvav (in-band),      dva1 (out-of-band/HLS)
#   AV1:   dav1 (out-of-band)
# =============================================================================


def format_dv_string(entry: str, profile: DVProfile, level: DVLevel) -> str:
    return f"{entry}.{profile.idc:02d}.{level.id:02d}"


# =============================================================================
# MASTER RESOLVER
# =============================================================================


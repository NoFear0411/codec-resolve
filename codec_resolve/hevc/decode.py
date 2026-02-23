"""
HEVC codec string decoder with full constraint byte analysis.

Decodes hvc1/hev1 strings into profile, level, tier, and constraint
flags with 14-check semantic validation.

Source: ISO/IEC 14496-15 Annex E, ITU-T H.265 Annex A.
"""
from typing import Dict, List, Optional, Tuple
from ..models import Chroma
from .levels import HEVCLevel, HEVC_LEVELS
from .profiles import HEVC_PROFILE_DEFS
from ..hls import strip_hls_brands


HEVC_PROFILE_NAMES = {
    1:  "Main",
    2:  "Main 10",
    3:  "Main Still Picture",
    4:  "Format Range Extensions (RExt)",
    5:  "High Throughput",
    6:  "Multiview Main",
    7:  "Scalable Main",
    8:  "Scalable Main 10",
    9:  "Screen Content Coding (SCC)",
    10: "Screen Content Coding 10-bit (SCC 10)",
    11: "High Throughput Screen Content Coding",
    12: "Scalable Range Extensions",
    13: "Multiview Range Extensions",
}

HEVC_PROFILE_SPACE_NAMES = {0: "(none)", 1: "A", 2: "B", 3: "C"}

# HEVC level lookup: level_idc → (level_number, max_luma_ps, max_luma_sps)
HEVC_LEVEL_LOOKUP = {lv.idc: lv for lv in HEVC_LEVELS}

def _decode_hevc_constraint_byte(byte_val: int, byte_idx: int,
                                  profile_idc: int = 0) -> List[Tuple[str, int]]:
    """Decode a single HEVC constraint byte into named flag tuples.

    Bytes 0-1: defined for ALL profiles (ITU-T H.265 Annex A).
    Byte 2:    extended "Precision Gate" for Profile 4+ (RExt/SCC).
               Per Annex A.3.5, these bits further constrain the decoder's
               depth, chroma, and coding capabilities beyond bytes 0-1.
    Byte 3:    SCC extension flags for Profile 9+ (screen content coding).
    Bytes 4-5: reserved (must be zero for all current profiles).
    """
    if byte_idx == 0:
        return [
            ("general_progressive_source",  (byte_val >> 7) & 1),
            ("general_interlaced_source",   (byte_val >> 6) & 1),
            ("general_non_packed_constraint",(byte_val >> 5) & 1),
            ("general_frame_only_constraint",(byte_val >> 4) & 1),
            ("general_max_12bit_constraint", (byte_val >> 3) & 1),
            ("general_max_10bit_constraint", (byte_val >> 2) & 1),
            ("general_max_8bit_constraint",  (byte_val >> 1) & 1),
            ("general_max_422chroma_constraint", (byte_val >> 0) & 1),
        ]
    elif byte_idx == 1:
        return [
            ("general_max_420chroma_constraint",  (byte_val >> 7) & 1),
            ("general_max_monochrome_constraint", (byte_val >> 6) & 1),
            ("general_inbld_flag",                (byte_val >> 5) & 1),
            ("general_one_picture_only_constraint",(byte_val >> 4) & 1),
            ("general_lower_bit_rate_constraint", (byte_val >> 3) & 1),
            ("general_max_14bit_constraint",      (byte_val >> 2) & 1),
            ("reserved[1:0]",                     (byte_val >> 0) & 3),
        ]
    elif byte_idx == 2 and profile_idc >= 4:
        # ── RExt/SCC Precision Gate (Byte 2) ─────────────────────
        # Per ITU-T H.265 Annex A.3.5 (Format Range Extensions),
        # byte 2 of the constraint indicator carries additional
        # precision and coding constraint flags for RExt profiles.
        #
        # These flags use NEGATIVE CONSTRAINT LOGIC: setting a bit
        # to 1 RESTRICTS the decoder. Clearing to 0 enables the
        # full capability of the profile.
        #
        # Bit layout (MSB → LSB):
        #   7: max_14bit  — if set, 16-bit samples prohibited
        #   6: max_12bit  — if set, 14-bit samples prohibited
        #   5: max_10bit  — if set, 12-bit samples prohibited
        #   4: max_8bit   — if set, 10-bit samples prohibited
        #   3: max_422    — if set, 4:4:4 chroma prohibited
        #   2: max_420    — if set, 4:2:2 chroma prohibited
        #   1: monochrome — if set, chroma prohibited entirely
        #   0: intra_only — if set, inter-prediction prohibited
        return [
            ("ext_max_14bit_constraint",    (byte_val >> 7) & 1),
            ("ext_max_12bit_constraint",    (byte_val >> 6) & 1),
            ("ext_max_10bit_constraint",    (byte_val >> 5) & 1),
            ("ext_max_8bit_constraint",     (byte_val >> 4) & 1),
            ("ext_max_422chroma_constraint",(byte_val >> 3) & 1),
            ("ext_max_420chroma_constraint",(byte_val >> 2) & 1),
            ("ext_max_monochrome_constraint",(byte_val >> 1) & 1),
            ("ext_intra_only_constraint",   (byte_val >> 0) & 1),
        ]
    elif byte_idx == 3 and profile_idc in (9, 10, 11):
        # ── SCC Extension Flags (Byte 3) ─────────────────────────
        # For Screen Content Coding profiles (9, 10, 11), byte 3
        # carries SCC-specific constraint flags per Annex A.3.7.
        #
        # Bit layout (MSB → LSB):
        #   7: no_palette_constraint      — palette mode prohibited
        #   6: no_ibc_constraint          — intra block copy prohibited
        #   5: no_act_constraint          — adaptive color transform off
        #   4: no_sao_constraint          — SAO filtering prohibited
        #   3: no_alf_constraint          — ALF prohibited
        #   2-0: reserved
        return [
            ("scc_no_palette_constraint",  (byte_val >> 7) & 1),
            ("scc_no_ibc_constraint",      (byte_val >> 6) & 1),
            ("scc_no_act_constraint",      (byte_val >> 5) & 1),
            ("scc_no_sao_constraint",      (byte_val >> 4) & 1),
            ("scc_no_alf_constraint",      (byte_val >> 3) & 1),
            ("scc_reserved[2:0]",          (byte_val >> 0) & 7),
        ]
    else:
        return [("reserved", byte_val)]


def _infer_rext_subprofile(flags: dict) -> str:
    """
    Infer the RExt sub-profile name from constraint flags.
    Only meaningful when profile_idc=4 (also 12, 13).

    Distinguishes intra-only vs inter-prediction variants:
      - one_picture_only=1  → "Still" suffix (single frame)
      - inbld=1 + no depth  → likely intra mastering layer
      - frame_only=1 (default) → predictive (standard streaming)

    Per ITU-T H.265 Annex A.3.5, RExt sub-profiles are named by
    combining chroma format, bit depth, and coding constraint.

    When byte 2 (Precision Gate) flags are present, they further
    constrain the effective depth/chroma — most restrictive wins.
    """
    # Byte 0-1 flags
    m12 = flags.get("general_max_12bit_constraint", 0)
    m10 = flags.get("general_max_10bit_constraint", 0)
    m8  = flags.get("general_max_8bit_constraint", 0)
    m14 = flags.get("general_max_14bit_constraint", 0)
    m422 = flags.get("general_max_422chroma_constraint", 0)
    m420 = flags.get("general_max_420chroma_constraint", 0)
    m_mono = flags.get("general_max_monochrome_constraint", 0)
    opo = flags.get("general_one_picture_only_constraint", 0)
    lbr = flags.get("general_lower_bit_rate_constraint", 0)

    # Byte 2 (Precision Gate) flags — merge with byte 0-1
    # Most restrictive constraint wins (OR the flags together)
    m8  = m8  or flags.get("ext_max_8bit_constraint", 0)
    m10 = m10 or flags.get("ext_max_10bit_constraint", 0)
    m12 = m12 or flags.get("ext_max_12bit_constraint", 0)
    m14 = m14 or flags.get("ext_max_14bit_constraint", 0)
    m422 = m422 or flags.get("ext_max_422chroma_constraint", 0)
    m420 = m420 or flags.get("ext_max_420chroma_constraint", 0)
    m_mono = m_mono or flags.get("ext_max_monochrome_constraint", 0)
    e_intra = flags.get("ext_intra_only_constraint", 0)

    # Determine max bit depth
    if m8:
        depth = "8-bit"
    elif m10:
        depth = "10-bit"
    elif m12:
        depth = "12-bit"
    elif m14:
        depth = "14-bit"
    else:
        depth = "≤16-bit"

    # Determine chroma
    if m_mono:
        chroma = "Monochrome"
    elif m420:
        chroma = "4:2:0"
    elif m422:
        chroma = "4:2:2"
    else:
        chroma = "4:4:4"

    # Coding constraint suffix
    # Per Annex A.3.5: "Intra" sub-profiles constrain to intra-only coding
    # one_picture_only → single frame (HEIF/still)
    # ext_intra_only from Precision Gate → all-intra stream
    # The "Still Picture" variant is when opo=1
    suffix = ""
    if opo:
        suffix = " Still Picture"
    elif e_intra:
        suffix = " Intra"

    # Build the name
    if m_mono:
        base = f"Monochrome {depth}" if depth != "8-bit" else "Monochrome"
    elif chroma == "4:2:0":
        base = f"Main {depth.replace('-bit', '')}" if depth != "8-bit" else "Main"
    elif chroma == "4:2:2":
        base = f"Main 4:2:2 {depth.replace('-bit', '')}"
    else:
        if depth == "8-bit":
            base = "Main 4:4:4"
        else:
            base = f"Main 4:4:4 {depth.replace('-bit', '')}"

    return f"{base}{suffix}"


def _infer_scc_subprofile(flags: dict, profile_idc: int) -> str:
    """
    Infer the SCC sub-profile name from constraint flags.
    Only meaningful when profile_idc in (9, 10, 11).

    Per ITU-T H.265 Annex A.3.7 (Screen Content Coding Extensions),
    SCC profiles add three key coding tools to the base profile:
      - Palette Mode: encodes flat-color regions (UI elements, text)
      - Intra Block Copy (IBC): copies blocks within the same frame
        (ideal for repeated screen elements like toolbars)
      - Adaptive Color Transform (ACT): RGB↔YCbCr conversion in-loop

    Byte 3 constraint flags can DISABLE these tools:
      scc_no_palette=1  → palette mode prohibited
      scc_no_ibc=1      → intra block copy prohibited
      scc_no_act=1      → adaptive color transform off
      scc_no_sao=1      → sample adaptive offset filtering off
      scc_no_alf=1      → adaptive loop filter off

    Disabling ALL SCC tools effectively reduces the profile to its
    base (Main for P9, Main 10 for P10, High Throughput for P11).
    """
    no_palette = flags.get("scc_no_palette_constraint", 0)
    no_ibc = flags.get("scc_no_ibc_constraint", 0)
    no_act = flags.get("scc_no_act_constraint", 0)
    no_sao = flags.get("scc_no_sao_constraint", 0)
    no_alf = flags.get("scc_no_alf_constraint", 0)

    # Determine active SCC tools
    tools = []
    if not no_palette:
        tools.append("Palette")
    if not no_ibc:
        tools.append("IBC")
    if not no_act:
        tools.append("ACT")

    # Filtering status
    filters = []
    if no_sao:
        filters.append("no-SAO")
    if no_alf:
        filters.append("no-ALF")

    # Base profile names
    base_names = {
        9:  "SCC",
        10: "SCC 10-bit",
        11: "High Throughput SCC",
    }
    base = base_names.get(profile_idc, f"SCC Profile {profile_idc}")

    # If all SCC tools are disabled, note the degradation
    if no_palette and no_ibc and no_act:
        fallback = {9: "Main", 10: "Main 10", 11: "High Throughput"}
        return (f"{base} (all SCC tools disabled — "
                f"effectively {fallback.get(profile_idc, 'base profile')})")

    # Build description
    parts = []
    if tools:
        parts.append(f"tools: {'+'.join(tools)}")
    if filters:
        parts.append(", ".join(filters))

    if parts:
        return f"{base} ({', '.join(parts)})"
    return base


def _validate_constraint_context(result: dict) -> List[dict]:
    """
    Semantic conflict resolver for HEVC constraint flags.

    The bit-level parser tells us WHAT flags are set. This function
    understands WHY certain flag combinations are contradictory,
    unexpected, or indicative of a specific workflow.

    Returns a list of validation findings, each with:
      severity: "error" | "warning" | "info"
      code: short machine-readable identifier
      message: human-readable explanation
      recommendation: suggested fix (optional)

    Conflict categories:
      1. Tier/bitrate contradictions
      2. Layer dependency implications
      3. Profile/constraint mismatches
      4. Scan mode contradictions
      5. RExt workflow classification
    """
    findings = []
    flags = result.get("constraint_flags", {})
    tier = result.get("tier", 0)
    tier_name = result.get("tier_name", "Main")
    profile_idc = result.get("profile_idc", 0)
    level_idc = result.get("level_idc", 0)

    lbr = flags.get("general_lower_bit_rate_constraint", 0)
    inbld = flags.get("general_inbld_flag", 0)
    prog = flags.get("general_progressive_source", 0)
    intl = flags.get("general_interlaced_source", 0)
    fo = flags.get("general_frame_only_constraint", 0)
    opo = flags.get("general_one_picture_only_constraint", 0)
    m8 = flags.get("general_max_8bit_constraint", 0)
    m10 = flags.get("general_max_10bit_constraint", 0)
    m12 = flags.get("general_max_12bit_constraint", 0)
    m14 = flags.get("general_max_14bit_constraint", 0)
    m422 = flags.get("general_max_422chroma_constraint", 0)
    m420 = flags.get("general_max_420chroma_constraint", 0)
    m_mono = flags.get("general_max_monochrome_constraint", 0)

    # ── 1. Tier vs Bitrate Constraint Contradiction ──────────────
    # High Tier exists specifically to allow higher bitrates than Main.
    # Asserting lower_bit_rate_constraint=1 on High Tier is contradictory:
    # you've opted into the higher bitrate tier, then immediately capped it.
    if tier == 1 and lbr:
        findings.append({
            "severity": "warning",
            "code": "HIGH_TIER_LBR",
            "message": (
                f"High Tier signaled but lower_bit_rate_constraint is set. "
                f"High Tier exists to allow bitrates above Main tier limits — "
                f"capping at the lower sub-tier (~⅔ of level max) contradicts "
                f"the reason for selecting High Tier"),
            "recommendation": (
                f"For uncapped High Tier: clear Byte 1 bit 3 "
                f"(lower_bit_rate_constraint=0). "
                f"If bitrate is genuinely capped, Main Tier may be "
                f"more appropriate"),
        })

    # ── 2. INBLD (Layer Dependency) Implications ─────────────────
    # general_inbld_flag=1 indicates this stream has intra boundary
    # layer dependency — it's a dependent layer in a scalable or
    # multi-layer system (e.g., Dolby Vision Enhancement Layer,
    # SHVC spatial layer, MV-HEVC dependent view).
    #
    # For standalone files (mastering, delivery, streaming), INBLD
    # should be 0. Its presence suggests this stream cannot be
    # independently decoded.
    if inbld:
        # Determine likely context from profile
        if profile_idc in (7, 8, 12):
            # Scalable profiles — INBLD is expected
            layer_context = ("scalable/SHVC layer (expected for "
                             f"Profile {profile_idc})")
        elif profile_idc in (6, 13):
            layer_context = ("multiview dependent view (expected for "
                             f"Profile {profile_idc})")
        else:
            # Profiles 1-4: standalone profiles — INBLD is unexpected
            layer_context = (
                "dependent/scalable layer in a multi-layer system "
                "(e.g., DV Enhancement Layer, SHVC spatial layer)")

        findings.append({
            "severity": ("info" if profile_idc in (6, 7, 8, 12, 13)
                         else "warning"),
            "code": "INBLD_SET",
            "message": (
                f"INBLD flag is set — this stream is a {layer_context}. "
                f"It requires its reference/base layer for correct decode "
                f"and cannot be played independently"),
            "recommendation": (
                None if profile_idc in (6, 7, 8, 12, 13) else
                "For standalone files (mastering, delivery, streaming), "
                "clear Byte 1 bit 5 (general_inbld_flag=0). "
                "If this IS a dependent layer, consider whether the "
                "profile_idc should be 7/8/12 (scalable) instead"),
        })

    # ── 2b. One-Picture-Only Contextual Warning ─────────────────
    # The one_picture_only_constraint_flag restricts the stream to a
    # single picture (no P/B frames, no temporal prediction).
    # This is expected for Profile 3 (Main Still Picture) and HEIF.
    # For any other profile, it means the encoder is claiming intra-only
    # which may be intentional (all-intra workflow) or a muxer bug.
    if opo:
        if profile_idc == 3:
            findings.append({
                "severity": "info",
                "code": "ONE_PICTURE_ONLY",
                "message": (
                    "one_picture_only constraint is set — consistent "
                    "with Profile 3 (Main Still Picture / HEIF)"),
                "recommendation": None,
            })
        elif profile_idc in (5, 11):
            # High Throughput profiles — intra-only is common
            findings.append({
                "severity": "info",
                "code": "ONE_PICTURE_ONLY",
                "message": (
                    "one_picture_only constraint is set — this is an "
                    "all-intra stream (no P/B frames). Expected for "
                    f"High Throughput Profile {profile_idc} in "
                    "professional editing workflows"),
                "recommendation": None,
            })
        else:
            findings.append({
                "severity": "warning",
                "code": "ONE_PICTURE_ONLY",
                "message": (
                    "one_picture_only constraint is set — stream is "
                    "restricted to a single picture (no temporal "
                    "prediction). Hardware decoders will not prepare "
                    "motion compensation buffers. If this is a video "
                    "file with GOP structure, this flag is incorrect"),
                "recommendation": (
                    "For video content, clear Byte 1 bit 4 "
                    "(general_one_picture_only_constraint=0). "
                    "If this IS a still image or all-intra file, "
                    "consider Profile 3 (Main Still Picture)"),
            })

    # ── 3. Scan Mode Contradictions ──────────────────────────────
    # progressive=1 + interlaced=1 = mixed content (valid but unusual)
    # progressive=0 + interlaced=0 = unknown scan (suspicious)
    # frame_only=1 + interlaced=1 = contradiction
    if fo and intl:
        findings.append({
            "severity": "error",
            "code": "FRAME_ONLY_INTERLACED",
            "message": (
                "frame_only_constraint=1 but interlaced_source=1 — "
                "frame_only prohibits field pictures, but interlaced "
                "source requires them. These flags are mutually exclusive"),
            "recommendation": (
                "For interlaced content: clear frame_only (Byte 0 bit 4). "
                "For progressive content: clear interlaced (Byte 0 bit 6)"),
        })

    if not prog and not intl:
        findings.append({
            "severity": "info",
            "code": "SCAN_UNKNOWN",
            "message": (
                "Neither progressive_source nor interlaced_source is set. "
                "Scan type is indeterminate — decoders cannot assume either"),
            "recommendation": (
                "Set progressive_source=1 (Byte 0 bit 7) for progressive "
                "content, or interlaced_source=1 (Byte 0 bit 6) for "
                "interlaced content"),
        })

    # ── 4. Depth Constraint Cascade Correctness ──────────────────
    # The depth constraint flags form a logical cascade:
    #   max_8bit=1 implies max_10bit=1, max_12bit=1, max_14bit=1
    #   max_10bit=1 implies max_12bit=1, max_14bit=1
    #   max_12bit=1 implies max_14bit=1
    #
    # If a lower depth is asserted but a higher one isn't, the
    # constraint set is internally inconsistent.
    depth_cascade = [
        (m8, "max_8bit", [m10, m12, m14], ["max_10bit", "max_12bit", "max_14bit"]),
        (m10, "max_10bit", [m12, m14], ["max_12bit", "max_14bit"]),
        (m12, "max_12bit", [m14], ["max_14bit"]),
    ]
    for flag_val, flag_name, implied_vals, implied_names in depth_cascade:
        if flag_val:
            for iv, iname in zip(implied_vals, implied_names):
                if not iv:
                    findings.append({
                        "severity": "error",
                        "code": "DEPTH_CASCADE_BROKEN",
                        "message": (
                            f"{flag_name}_constraint=1 implies "
                            f"{iname}_constraint=1, but {iname} is clear. "
                            f"A stream limited to {flag_name.split('_')[1]} "
                            f"is also limited to {iname.split('_')[1]}"),
                        "recommendation": (
                            f"Set {iname}_constraint=1 to fix the cascade, "
                            f"or clear {flag_name}_constraint=0 if the "
                            f"tighter limit is incorrect"),
                    })
                    break  # Report first break in chain only

    # ── 5. Chroma Constraint Cascade Correctness ─────────────────
    # monochrome=1 implies max_420=1, max_422=1
    # max_420=1 implies max_422=1
    if m_mono and not m420:
        findings.append({
            "severity": "error",
            "code": "CHROMA_CASCADE_BROKEN",
            "message": (
                "max_monochrome=1 implies max_420chroma=1 "
                "(monochrome ⊂ 4:2:0 ⊂ 4:2:2), "
                "but max_420chroma is clear"),
            "recommendation": "Set max_420chroma=1 and max_422chroma=1",
        })
    if m420 and not m422:
        findings.append({
            "severity": "error",
            "code": "CHROMA_CASCADE_BROKEN",
            "message": (
                "max_420chroma=1 implies max_422chroma=1 "
                "(4:2:0 ⊂ 4:2:2), but max_422chroma is clear"),
            "recommendation": "Set max_422chroma=1",
        })

    # ── 6. Profile vs Constraint Flag Consistency ──────────────────
    # Profiles 1-3 have FIXED depth/chroma: hardware allocates a
    # specific buffer regardless of constraint flags. Extended
    # constraint bits (depth, chroma, monochrome) are ignored by
    # decoders for these profiles.
    #
    # Three sub-checks:
    #   a) Constraint flags BEYOND the profile's scope (impossible claims)
    #   b) Constraint flags WEAKER than the profile enforces
    #   c) Flag the result so stream_info can annotate override
    pdef = HEVC_PROFILE_DEFS.get(profile_idc)
    profile_overrides = False  # track if P1-3 constraint flags are suspect

    if pdef and profile_idc in (1, 2, 3):
        # Profile capability limits
        p_max_d = pdef.max_depth       # 8 for P1/P3, 10 for P2
        p_420_only = Chroma.YUV422 not in pdef.chroma_set

        # 6a: Impossible constraint claims — flags claim capabilities the
        #     profile cannot provide. Hardware ignores these entirely.
        #     Example: Profile 2 + monochrome flag, or P2 + max_14bit
        impossible = []

        if m_mono and p_420_only:
            # P1-3 are 4:2:0 only — monochrome constraint is meaningless
            impossible.append("monochrome (profile is 4:2:0 only)")

        if m14 and p_max_d < 14:
            impossible.append(f"max_14bit (profile max is {p_max_d}-bit)")
        if m12 and p_max_d < 12:
            impossible.append(f"max_12bit (profile max is {p_max_d}-bit)")

        # For P1: max_10bit is beyond 8-bit profile
        if m10 and not m8 and p_max_d == 8:
            impossible.append(f"max_10bit without max_8bit "
                              f"(profile max is {p_max_d}-bit)")

        if impossible:
            profile_overrides = True
            findings.append({
                "severity": "warning",
                "code": "PROFILE_CONSTRAINT_IMPOSSIBLE",
                "message": (
                    f"Profile {profile_idc} ({pdef.name}) is limited to "
                    f"{p_max_d}-bit 4:2:0 — hardware decoders ignore "
                    f"extended constraint flags for this profile. "
                    f"Impossible claims: {', '.join(impossible)}"),
                "recommendation": (
                    f"Clear the extended constraint bits for Profile "
                    f"{profile_idc}. These flags have no effect on "
                    f"decoder behavior and may confuse validators"),
            })

        # 6b: Weaker-than-profile constraints
        # e.g., P1 (8-bit) with only max_12bit=1 → weaker, misleading
        elif any([m10, m12, m14]) and not m8 and p_max_d == 8:
            findings.append({
                "severity": "info",
                "code": "CONSTRAINT_WEAKER_THAN_PROFILE",
                "message": (
                    f"Profile {profile_idc} ({pdef.name}) is limited "
                    f"to {p_max_d}-bit, but the depth constraint "
                    f"flags assert a weaker limit. The profile enforces "
                    f"the tighter constraint regardless"),
                "recommendation": None,
            })
        elif any([m10, m12, m14]) and not m8 and p_max_d == 10:
            # P2 with max_12bit but no max_10bit → weaker
            weaker = ("≤12-bit" if m12 else "≤14-bit" if m14 else
                      "≤16-bit")
            findings.append({
                "severity": "info",
                "code": "CONSTRAINT_WEAKER_THAN_PROFILE",
                "message": (
                    f"Profile {profile_idc} ({pdef.name}) is limited "
                    f"to {p_max_d}-bit, but the depth constraint "
                    f"flags assert a weaker limit ({weaker}). "
                    f"The profile enforces the tighter constraint"),
                "recommendation": None,
            })

    # Expose override flag for stream_info annotation
    result["_profile_overrides_constraints"] = profile_overrides

    # ── 7. Compat Flags vs Profile Definition ──────────────────────
    # Per ITU-T H.265 Annex A, each profile defines a specific set of
    # general_profile_compatibility_flag bits. The profile's own bit
    # MUST be set (self-signaling), and the complete set must match.
    #
    # Cross-reference categories:
    #   a) Self-bit missing: profile_idc's own bit not set → error
    #   b) Required bits missing: spec-defined compat bits absent → error
    #   c) Extra bits set: bits outside the defined set → warning
    compat_flags = result.get("compatibility_flags", 0)
    pdef = HEVC_PROFILE_DEFS.get(profile_idc)

    if pdef:
        expected_bits = pdef.compat_bits  # e.g., {1, 2} for Main, {2} for Main 10

        # a) Self-bit: profile_idc's own bit must be set
        self_bit_set = bool(compat_flags & (1 << profile_idc))
        if not self_bit_set:
            findings.append({
                "severity": "error",
                "code": "COMPAT_SELF_BIT_MISSING",
                "message": (
                    f"Profile {profile_idc} ({pdef.name}) self-bit "
                    f"(bit {profile_idc}) is not set in compatibility flags "
                    f"(0x{compat_flags:X}). Per ITU-T H.265 Annex A, each "
                    f"profile must signal its own profile_idc in the "
                    f"compatibility flags"),
                "recommendation": (
                    f"Set bit {profile_idc} in compatibility flags. "
                    f"Expected: 0x{sum(1 << b for b in expected_bits):X}"),
            })

        # b) Required bits: all defined compat bits must be present
        missing_bits = []
        for bit in sorted(expected_bits):
            if not (compat_flags & (1 << bit)):
                bit_name = HEVC_PROFILE_NAMES.get(bit, f"profile {bit}")
                missing_bits.append(f"bit {bit} ({bit_name})")

        if missing_bits:
            expected_hex = sum(1 << b for b in expected_bits)
            findings.append({
                "severity": "error",
                "code": "COMPAT_BITS_INCOMPLETE",
                "message": (
                    f"Profile {profile_idc} ({pdef.name}) requires "
                    f"compatibility bits {sorted(expected_bits)}, "
                    f"but missing: {', '.join(missing_bits)}. "
                    f"Current flags: 0x{compat_flags:X}"),
                "recommendation": (
                    f"Set compatibility flags to 0x{expected_hex:X} "
                    f"(bits {sorted(expected_bits)})"),
            })

        # c) Extra bits: bits set that aren't in the profile's defined set
        extra_bits = []
        for bit in range(32):
            if (compat_flags & (1 << bit)) and bit not in expected_bits:
                bit_name = HEVC_PROFILE_NAMES.get(bit, f"profile {bit}")
                extra_bits.append(f"bit {bit} ({bit_name})")

        if extra_bits:
            expected_hex = sum(1 << b for b in expected_bits)
            findings.append({
                "severity": "warning",
                "code": "COMPAT_BITS_EXTRA",
                "message": (
                    f"Compatibility flags 0x{compat_flags:X} contain "
                    f"bits outside Profile {profile_idc}'s defined set "
                    f"{sorted(expected_bits)}: {', '.join(extra_bits)}. "
                    f"These may indicate a muxer/encoder bug or intentional "
                    f"cross-profile signaling"),
                "recommendation": (
                    f"Standard flags for Profile {profile_idc}: "
                    f"0x{expected_hex:X}. Extra bits are technically "
                    f"valid (decoders should accept) but non-standard"),
            })

    # ── 8. High Tier vs Level Capability ─────────────────────────
    # Per ITU-T H.265 Table A.6, High Tier is only defined for
    # Levels ≥ 4.0 (level_idc ≥ 120). Lower levels have only Main.
    # Signaling High Tier on a level that doesn't support it is
    # spec-invalid — decoders may reject or ignore it.
    if tier == 1:
        hevc_lv = HEVC_LEVEL_LOOKUP.get(level_idc)
        if hevc_lv and not hevc_lv.has_high_tier:
            findings.append({
                "severity": "error",
                "code": "TIER_INVALID_FOR_LEVEL",
                "message": (
                    f"High Tier signaled but Level {hevc_lv.number} "
                    f"(level_idc={level_idc}) does not define a High Tier. "
                    f"Per ITU-T H.265 Table A.6, High Tier is only "
                    f"available at Level 4.0 and above"),
                "recommendation": (
                    f"Change tier to Main (L{level_idc} instead of "
                    f"H{level_idc}), or use Level ≥ 4.0 "
                    f"(level_idc ≥ 120) if High Tier bitrates are needed"),
            })
        elif not hevc_lv:
            # Non-standard level_idc — can't verify
            findings.append({
                "severity": "warning",
                "code": "LEVEL_UNKNOWN",
                "message": (
                    f"level_idc={level_idc} is not a standard HEVC level. "
                    f"Cannot verify if High Tier is valid"),
                "recommendation": (
                    f"Standard level_idc values: "
                    f"30, 60, 63, 90, 93, 120, 123, 150, 153, 156, "
                    f"180, 183, 186"),
            })

    # ── 9. Reserved & Extended Constraint Bytes ─────────────────
    # Per ITU-T H.265 Annex A, the meaning of constraint bytes
    # depends on the profile:
    #
    # Profiles 1-3 (Main, Main 10, Main Still Picture):
    #   Bytes 0-1: defined flags (source, depth, chroma, LBR)
    #   Bytes 2-5: reserved — MUST be zero
    #
    # Profile 4+ (RExt, HT, SCC, Scalable, Multiview):
    #   Byte 2:   Precision Gate — extended depth/chroma/intra constraints
    #             per Annex A.3.5 (RExt Format Range Extensions)
    #   Byte 3:   SCC extensions for Profile 9-11 (Annex A.3.7)
    #   Bytes 4-5: reserved — should be zero
    #
    cbytes = result.get("constraint_bytes_int", [0] * 6)
    n_present = result.get("constraint_bytes_present", 0)

    if n_present > 2:
        if profile_idc in (1, 2, 3):
            # Profiles 1-3: bytes 2-5 all reserved — MUST be zero
            for i in range(2, min(n_present, 6)):
                if cbytes[i] != 0:
                    findings.append({
                        "severity": "error",
                        "code": "RESERVED_BYTE_NONZERO",
                        "message": (
                            f"Constraint byte {i} is 0x{cbytes[i]:02X} "
                            f"but must be 0x00 for Profile {profile_idc} "
                            f"({pdef.name if pdef else '?'}). "
                            f"Bytes 2-5 are reserved for this profile "
                            f"per ITU-T H.265 Annex A"),
                        "recommendation": (
                            f"Set byte {i} to 0x00. Non-zero reserved "
                            f"bytes may cause decoder rejection"),
                    })
        else:
            # ── 9a. Precision Gate Validation (Byte 2) ───────────
            # For Profile 4+, byte 2 carries extended precision flags.
            # Validate internal consistency and cross-check with bytes 0-1.
            if n_present >= 3 and cbytes[2] != 0:
                em8  = flags.get("ext_max_8bit_constraint", 0)
                em10 = flags.get("ext_max_10bit_constraint", 0)
                em12 = flags.get("ext_max_12bit_constraint", 0)
                em14 = flags.get("ext_max_14bit_constraint", 0)
                em422 = flags.get("ext_max_422chroma_constraint", 0)
                em420 = flags.get("ext_max_420chroma_constraint", 0)
                em_mono = flags.get("ext_max_monochrome_constraint", 0)
                e_intra = flags.get("ext_intra_only_constraint", 0)

                # Depth cascade: 8 ⊂ 10 ⊂ 12 ⊂ 14
                # If max_8bit is set, all higher should be set
                if em8 and not em10:
                    findings.append({
                        "severity": "error",
                        "code": "PRECISION_GATE_DEPTH_CASCADE",
                        "message": (
                            "Byte 2 Precision Gate: ext_max_8bit=1 but "
                            "ext_max_10bit=0. If depth is ≤8-bit, the "
                            "10/12/14-bit constraints must also be set "
                            "(8 ⊂ 10 ⊂ 12 ⊂ 14)"),
                        "recommendation": (
                            "Set byte 2 to 0xF0 for 8-bit lock, or "
                            "clear the cascade: 0xE0=10-bit, 0xC0=12-bit, "
                            "0x80=14-bit"),
                    })

                # Chroma cascade: mono ⊂ 420 ⊂ 422
                if em_mono and not em420:
                    findings.append({
                        "severity": "error",
                        "code": "PRECISION_GATE_CHROMA_CASCADE",
                        "message": (
                            "Byte 2 Precision Gate: ext_monochrome=1 but "
                            "ext_max_420=0. Monochrome implies 4:2:0 "
                            "and 4:2:2 constraints (mono ⊂ 420 ⊂ 422)"),
                        "recommendation": (
                            "Set byte 2 chroma bits to 0x0E for "
                            "monochrome lock"),
                    })
                if em420 and not em422:
                    findings.append({
                        "severity": "error",
                        "code": "PRECISION_GATE_CHROMA_CASCADE",
                        "message": (
                            "Byte 2 Precision Gate: ext_max_420=1 but "
                            "ext_max_422=0. 4:2:0 implies 4:2:2 "
                            "constraint (420 ⊂ 422)"),
                        "recommendation": "Set ext_max_422=1 in byte 2",
                    })

                # Cross-check: byte 2 vs byte 0-1 depth conflict
                # If byte 0-1 has no depth constraint but byte 2 does,
                # that's the precision gate doing its job (valid)
                # If byte 0-1 says ≤8bit but byte 2 says ≤12bit (weaker),
                # byte 0-1 wins — flag the inconsistency
                if m8 and not em8 and (em10 or em12 or em14):
                    findings.append({
                        "severity": "warning",
                        "code": "PRECISION_GATE_DEPTH_CONFLICT",
                        "message": (
                            "Byte 0-1 constrains to ≤8-bit "
                            "(max_8bit=1), but Byte 2 precision gate "
                            "signals a weaker depth limit. "
                            "Byte 0-1 constraint takes precedence"),
                        "recommendation": (
                            "Align byte 2 depth flags with byte 0-1 "
                            "or clear byte 2"),
                    })

            # ── 9b. SCC Extension Validation (Byte 3) ────────────
            # For Profile 9-11, byte 3 has SCC-specific flags.
            # Remaining reserved bytes start at byte 4 for SCC
            # profiles, byte 3 for other Profile 4+ profiles.
            reserved_start = 4 if profile_idc in (9, 10, 11) else 3
            for i in range(reserved_start, min(n_present, 6)):
                if cbytes[i] != 0:
                    findings.append({
                        "severity": "warning",
                        "code": "RESERVED_BYTE_NONZERO",
                        "message": (
                            f"Constraint byte {i} is 0x{cbytes[i]:02X} "
                            f"but bytes {reserved_start}-5 are reserved "
                            f"and should be 0x00. This may indicate an "
                            f"encoder bug or non-standard extension"),
                        "recommendation": (
                            f"Set byte {i} to 0x00 unless a specific "
                            f"extension is intentionally using it"),
                    })

    # ── 10. RExt Workflow Classification ──────────────────────────
    # For RExt (Profile 4), the combination of flags reveals the
    # intended workflow:
    #
    # Mastering/Professional Intra:
    #   High Tier + no depth/chroma constraints + INBLD=0
    #   → Unconstrained RExt for maximum quality
    #
    # Streaming/Delivery:
    #   Main Tier + depth/chroma constraints + LBR=1
    #   → Constrained RExt sub-profile for device compatibility
    #
    # Dependent Layer:
    #   INBLD=1 → part of a multi-layer system
    if profile_idc in (4, 12, 13):
        has_any_depth = m8 or m10 or m12 or m14
        has_any_chroma = m_mono or m420 or m422

        if inbld:
            workflow = "Dependent layer (multi-layer/scalable system)"
        elif tier == 1 and not has_any_depth and not has_any_chroma and not lbr:
            workflow = "Professional mastering (unconstrained High Tier RExt)"
        elif tier == 1 and not has_any_depth and not has_any_chroma and lbr:
            workflow = ("Professional mastering (High Tier) — "
                        "but bitrate is sub-tier capped (see HIGH_TIER_LBR)")
        elif lbr and (has_any_depth or has_any_chroma):
            workflow = "Streaming/delivery (constrained sub-profile)"
        elif not has_any_depth and not has_any_chroma:
            workflow = "General RExt (unconstrained Main Tier)"
        else:
            workflow = "Constrained RExt (depth/chroma limited)"

        findings.append({
            "severity": "info",
            "code": "REXT_WORKFLOW",
            "message": f"RExt workflow classification: {workflow}",
            "recommendation": None,
        })

    # ── 12. RExt Excessive Profile Detection ─────────────────────
    # If RExt (Profile 4) constraint flags reduce the effective
    # capability to match Profile 1 (Main) or Profile 2 (Main 10),
    # the profile is excessive — a simpler profile would suffice
    # with better hardware compatibility.
    #
    # The check uses BOTH byte 0 and byte 2 flags (most restrictive
    # wins via the precision gate logic).
    if profile_idc == 4:
        # Effective depth: most restrictive of byte 0 and byte 2
        eff_8bit = m8 or flags.get("ext_max_8bit_constraint", 0)
        eff_10bit = m10 or flags.get("ext_max_10bit_constraint", 0)

        # Effective chroma: most restrictive of byte 0 and byte 2
        eff_420 = m420 or flags.get("ext_max_420chroma_constraint", 0)
        eff_mono = m_mono or flags.get("ext_max_monochrome_constraint", 0)

        # Profile 1 territory: ≤4:2:0, ≤8-bit, NOT monochrome-only
        if eff_8bit and eff_420 and not eff_mono:
            findings.append({
                "severity": "info",
                "code": "REXT_EXCESSIVE_PROFILE",
                "message": (
                    "Profile 4 (RExt) is constrained to ≤8-bit ≤4:2:0 by "
                    "constraint flags — this is within Profile 1 (Main) "
                    "capability. RExt adds no benefit here and reduces "
                    "hardware compatibility"),
                "recommendation": (
                    "Use Profile 1 (Main) instead. Profile 1 is decoded "
                    "by all HEVC hardware, while RExt requires specialized "
                    "decoder support"),
            })
        # Profile 2 territory: ≤4:2:0, ≤10-bit
        elif eff_10bit and eff_420 and not eff_mono:
            findings.append({
                "severity": "info",
                "code": "REXT_EXCESSIVE_PROFILE",
                "message": (
                    "Profile 4 (RExt) is constrained to ≤10-bit ≤4:2:0 "
                    "by constraint flags — this is within Profile 2 "
                    "(Main 10) capability. RExt adds no benefit here and "
                    "reduces hardware compatibility"),
                "recommendation": (
                    "Use Profile 2 (Main 10) instead. Profile 2 is widely "
                    "supported on consumer hardware (TVs, phones, tablets), "
                    "while RExt requires professional decoder support"),
            })

    # ── 13. Intra-Only Constraint Warning ────────────────────────
    # ext_intra_only_constraint (Byte 2, bit 0) prohibits ALL
    # inter-prediction (no P-frames, no B-frames). The stream is
    # restricted to I-frames only.
    #
    # This is legitimate for:
    #   - Professional intra mastering (XAVC Intra, ProRes-like workflows)
    #   - HEIF/AVCI still image sequences
    #   - All-intra archival encoding
    #
    # But it's a CRITICAL issue if the actual stream contains GOPs
    # with P/B frames — a decoder honoring this flag will crash or
    # reject frames with inter-prediction references.
    ext_intra = flags.get("ext_intra_only_constraint", 0)
    if ext_intra:
        findings.append({
            "severity": "warning",
            "code": "INTRA_ONLY_CONSTRAINT",
            "message": (
                "Intra-only constraint is set (Byte 2, bit 0). "
                "Inter-prediction (P-frames, B-frames) is prohibited. "
                "If the actual stream contains a GOP with predictive "
                "frames, hardware decoders will reject them — causing "
                "frame drops, corruption, or decoder crash"),
            "recommendation": (
                "Verify the source is genuinely all-intra (e.g., "
                "XAVC Intra, archival). If the stream has P/B frames, "
                "clear Byte 2 bit 0 (ext_intra_only_constraint=0)"),
        })

    # ── 14. SCC Tool Validation (Profile 9/10/11) ────────────────
    # For Screen Content Coding profiles, byte 3 flags control
    # which SCC-specific coding tools are available.
    #
    # Key tools: Palette, IBC (Intra Block Copy), ACT
    # If ALL are disabled, the profile degrades to its base (Main/Main 10/HT)
    # and the SCC profile_idc is misleading.
    if profile_idc in (9, 10, 11):
        no_pal = flags.get("scc_no_palette_constraint", 0)
        no_ibc = flags.get("scc_no_ibc_constraint", 0)
        no_act = flags.get("scc_no_act_constraint", 0)

        # Check if byte 3 flags are present
        cbytes = result.get("constraint_bytes_int", [0] * 6)
        n_present = result.get("constraint_bytes_present", 0)
        has_byte3 = n_present >= 4

        if has_byte3:
            if no_pal and no_ibc and no_act:
                # All SCC tools disabled — effectively base profile
                fallback = {9: "Main (Profile 1)", 10: "Main 10 (Profile 2)",
                            11: "High Throughput (Profile 5)"}
                findings.append({
                    "severity": "warning",
                    "code": "SCC_ALL_TOOLS_DISABLED",
                    "message": (
                        f"All SCC coding tools are disabled (Palette, "
                        f"IBC, ACT all prohibited by Byte 3 constraints). "
                        f"Profile {profile_idc} is effectively "
                        f"{fallback.get(profile_idc, 'base profile')} "
                        f"with no screen content advantage"),
                    "recommendation": (
                        f"Use {fallback.get(profile_idc, 'base profile')} "
                        f"instead, or enable at least one SCC tool "
                        f"(Palette or IBC) in Byte 3"),
                })
            elif no_ibc and not no_pal:
                # IBC disabled but Palette active — unusual but valid
                # IBC is the primary SCC tool; Palette without IBC has
                # limited utility for typical screen content
                findings.append({
                    "severity": "info",
                    "code": "SCC_IBC_DISABLED",
                    "message": (
                        "IBC (Intra Block Copy) is disabled but Palette "
                        "mode is active. IBC is the primary SCC tool for "
                        "screen capture — Palette alone is less effective "
                        "for typical screen content workflows"),
                    "recommendation": None,
                })
            else:
                # At least IBC active — standard SCC operation
                active = []
                if not no_pal:
                    active.append("Palette")
                if not no_ibc:
                    active.append("IBC")
                if not no_act:
                    active.append("ACT")
                findings.append({
                    "severity": "info",
                    "code": "SCC_TOOLS_ACTIVE",
                    "message": (
                        f"SCC tools active: {', '.join(active)}"),
                    "recommendation": None,
                })
        else:
            # No byte 3 — SCC tools are all enabled by default
            findings.append({
                "severity": "info",
                "code": "SCC_TOOLS_ACTIVE",
                "message": (
                    "SCC tools: all enabled (Palette, IBC, ACT) — "
                    "no Byte 3 constraints present"),
                "recommendation": None,
            })

    return findings


def decode_hevc(codec_string: str) -> dict:
    """
    Decode an HEVC codec string into all its component fields.

    Input:  "hvc1.2.4.L150.BD.88"
    Output: dict with entry, profile, level, tier, constraint flags, etc.

    Also accepts HLS SUPPLEMENTAL-CODECS brand suffix (RFC 8216bis §4.4.6.2):
      "hvc1.2.20000000.L123.B0/cdm4"
    The brand is stripped before parsing and stored as metadata.
    """
    # ── HLS brand stripping ──
    codec_string, hls_brands, _unknown = strip_hls_brands(codec_string)

    parts = codec_string.split(".")
    if len(parts) < 4:
        raise ValueError(
            f"Invalid HEVC codec string: '{codec_string}'. "
            f"Expected at least 4 dot-separated components: "
            f"<entry>.<profile>.<compat>.<tier+level>[.<constraints>...]")

    result = {"codec_string": codec_string, "family": "hevc"}

    # Store HLS brand info if present
    if hls_brands:
        result["hls_brands"] = hls_brands
        brand_suffix = "/".join(b["brand"] for b in hls_brands)
        result["codec_string_full"] = f"{codec_string}/{brand_suffix}"

    # 1. Entry point
    entry = parts[0]
    if entry not in ("hvc1", "hev1"):
        raise ValueError(f"Unknown HEVC entry: '{entry}'. Expected hvc1 or hev1.")
    result["entry"] = entry
    result["entry_meaning"] = ("Parameter sets out of band (sample entry)"
                               if entry == "hvc1"
                               else "Parameter sets in band (each sample)")

    # 2. Profile space + profile IDC
    profile_str = parts[1]
    profile_space = 0
    if profile_str and profile_str[0] in "ABCabc":
        profile_space = {"A": 1, "B": 2, "C": 3,
                         "a": 1, "b": 2, "c": 3}[profile_str[0]]
        profile_idc = int(profile_str[1:])
    else:
        profile_idc = int(profile_str)

    result["profile_space"] = profile_space
    result["profile_space_name"] = HEVC_PROFILE_SPACE_NAMES.get(profile_space, "?")
    result["profile_idc"] = profile_idc
    result["profile_name"] = HEVC_PROFILE_NAMES.get(profile_idc,
                                                     f"Unknown (profile {profile_idc})")

    # Enrich with spec metadata from profile definition table
    pdef = HEVC_PROFILE_DEFS.get(profile_idc)
    if pdef:
        depth_label = ("8" if pdef.max_depth == 8
                       else f"8-{pdef.max_depth}")
        chroma_strs = []
        for ch in [Chroma.MONO, Chroma.YUV420, Chroma.YUV422, Chroma.YUV444]:
            if ch in pdef.chroma_set:
                chroma_strs.append(str(ch))
        result["profile_max_depth"] = f"{depth_label}-bit"
        result["profile_chroma_support"] = ", ".join(chroma_strs)
        if pdef.note:
            result["profile_note"] = pdef.note
    else:
        result["profile_max_depth"] = "unknown"
        result["profile_chroma_support"] = "unknown"

    # 3. Compatibility flags (32-bit hex)
    compat_hex = parts[2]
    compat_flags = int(compat_hex, 16)
    result["compatibility_flags"] = compat_flags
    result["compatibility_flags_hex"] = f"0x{compat_flags:08X}"

    # Decode which profiles this stream is backward-compatible with
    compat_profiles = []
    for bit in range(32):
        if compat_flags & (1 << bit):
            name = HEVC_PROFILE_NAMES.get(bit, f"profile {bit}")
            compat_profiles.append(f"{bit} ({name})")
    result["compatible_with_profiles"] = compat_profiles

    # 4. Tier + Level IDC
    tier_level = parts[3]
    if tier_level[0] in "LlMm":
        tier = 0
        tier_name = "Main"
    elif tier_level[0] in "Hh":
        tier = 1
        tier_name = "High"
    else:
        raise ValueError(f"Unknown tier indicator: '{tier_level[0]}'. Expected L or H.")

    level_idc = int(tier_level[1:])
    result["tier"] = tier
    result["tier_name"] = tier_name
    result["level_idc"] = level_idc

    # Lookup level details
    lv = HEVC_LEVEL_LOOKUP.get(level_idc)
    if lv:
        result["level_number"] = lv.number
        result["level_max_luma_ps"] = lv.max_luma_ps
        result["level_max_luma_sps"] = lv.max_luma_sps
        result["level_max_bitrate"] = (lv.max_br_high if tier == 1
                                       else lv.max_br_main)
        result["level_max_bitrate_label"] = f"{result['level_max_bitrate']:,} kbps"
        result["level_has_high_tier"] = lv.has_high_tier

        # Infer max resolution from luma_ps
        # Common resolutions
        res_map = [
            (36864,    "720×480 (480p)"),
            (122880,   "720×576 (576p)"),
            (245760,   "960×540"),
            (552960,   "1280×720 (720p)"),
            (983040,   "1280×768"),
            (2228224,  "1920×1080 (1080p)"),
            (8912896,  "3840×2160 (4K UHD)"),
            (35651584, "7680×4320 (8K UHD)"),
        ]
        max_res = "unknown"
        for ps, label in res_map:
            if lv.max_luma_ps >= ps:
                max_res = label
        result["level_max_resolution"] = max_res
    else:
        result["level_number"] = level_idc / 30.0
        result["level_max_resolution"] = "unknown (non-standard level_idc)"

    # 5. Constraint bytes (optional, 0-6 bytes)
    #
    # Per ISO/IEC 14496-15 Annex E, constraint bytes are dot-separated hex:
    #   hvc1.4.10.H153.B0.28.00.00.00.00
    #
    # Some tools emit them as a single blob without dots:
    #   hvc1.4.10.H153.B02800000000
    #
    # We handle both: if a component is >0xFF, split it into byte pairs.
    constraint_bytes = []
    constraint_warnings = []
    for i in range(4, min(len(parts), 10)):
        hex_str = parts[i]
        val = int(hex_str, 16)
        if val > 0xFF:
            # Oversized — split into individual bytes (big-endian)
            # Pad to even length for clean byte splitting
            padded = hex_str if len(hex_str) % 2 == 0 else "0" + hex_str
            for j in range(0, len(padded), 2):
                constraint_bytes.append(int(padded[j:j+2], 16))
            constraint_warnings.append(
                f"Constraint component '{hex_str}' is >1 byte — "
                f"auto-split into {len(padded)//2} bytes. "
                f"Spec requires dot-separated hex: "
                f"{'.'.join(padded[j:j+2].upper() for j in range(0, len(padded), 2))}")
        else:
            constraint_bytes.append(val)

    # Truncate to max 6 bytes per spec, pad if fewer
    constraint_bytes = constraint_bytes[:6]
    n_actual = len(constraint_bytes)
    while len(constraint_bytes) < 6:
        constraint_bytes.append(0)

    result["constraint_bytes_raw"] = [f"0x{b:02X}" for b in constraint_bytes[:6]]
    result["constraint_bytes_int"] = list(constraint_bytes[:6])  # For validator
    result["constraint_bytes_present"] = n_actual
    if constraint_warnings:
        result["constraint_warnings"] = constraint_warnings

    # Decode all flag bits
    all_flags = {}
    # Bytes 0-1: always decoded (all profiles)
    # Byte 2: decoded for Profile 4+ (RExt precision gate)
    # Byte 3: decoded for Profile 9-11 (SCC extension flags)
    # Bytes 4-5: always reserved
    max_decode = 2  # bytes 0-1 always
    if profile_idc >= 4:
        max_decode = 3  # add byte 2 (precision gate)
    if profile_idc in (9, 10, 11):
        max_decode = 4  # add byte 3 (SCC extension)
    for i in range(min(max_decode, n_actual, 6)):
        for name, val in _decode_hevc_constraint_byte(
                constraint_bytes[i], i, profile_idc):
            all_flags[name] = val
    result["constraint_flags"] = all_flags

    # Derive STREAM-SPECIFIC characteristics from constraint flags
    # These describe THIS exact stream, not the profile's theoretical range.
    stream = {}

    # Source type
    prog = all_flags.get("general_progressive_source", 0)
    intl = all_flags.get("general_interlaced_source", 0)
    if prog and not intl:
        stream["scan"] = "Progressive"
    elif intl and not prog:
        stream["scan"] = "Interlaced"
    elif prog and intl:
        stream["scan"] = "Mixed (progressive + interlaced)"
    else:
        stream["scan"] = "Unknown (neither flag set)"

    fo = all_flags.get("general_frame_only_constraint", 0)
    stream["frame_only"] = "Yes — no field coding" if fo else "No — field pictures allowed"

    np = all_flags.get("general_non_packed_constraint", 0)
    stream["non_packed"] = "Yes" if np else "No — packed frame arrangement possible"

    opo = all_flags.get("general_one_picture_only_constraint", 0)
    if opo:
        stream["one_picture_only"] = "Yes — single frame (still image / HEIF)"

    inbld = all_flags.get("general_inbld_flag", 0)
    if inbld:
        # Contextual INBLD labeling based on profile
        if profile_idc in (7, 8, 12):
            stream["inbld"] = ("Yes — dependent scalable layer "
                               f"(expected for Profile {profile_idc})")
        elif profile_idc in (6, 13):
            stream["inbld"] = ("Yes — dependent multiview layer "
                               f"(expected for Profile {profile_idc})")
        else:
            stream["inbld"] = ("Yes — dependent/scalable layer "
                               "(unexpected for standalone Profile "
                               f"{profile_idc} — see validation below)")

    # Bit depth: what does this stream actually allow?
    m8 = all_flags.get("general_max_8bit_constraint", 0)
    m10 = all_flags.get("general_max_10bit_constraint", 0)
    m12 = all_flags.get("general_max_12bit_constraint", 0)
    m14 = all_flags.get("general_max_14bit_constraint", 0)

    # Resolve concrete max from profile def
    profile_max_d = pdef.max_depth if pdef else 16

    if m8:
        stream["bit_depth"] = "≤8-bit"
    elif m10:
        stream["bit_depth"] = "≤10-bit"
    elif m12:
        stream["bit_depth"] = "≤12-bit"
    elif m14:
        stream["bit_depth"] = "≤14-bit"
    else:
        stream["bit_depth"] = (f"≤{profile_max_d}-bit "
                                f"(no depth constraint — profile maximum)")

    # Chroma: what does this stream actually allow?
    m_mono = all_flags.get("general_max_monochrome_constraint", 0)
    m420 = all_flags.get("general_max_420chroma_constraint", 0)
    m422 = all_flags.get("general_max_422chroma_constraint", 0)

    if m_mono:
        stream["chroma"] = "Monochrome only"
    elif m420:
        stream["chroma"] = "≤4:2:0"
    elif m422:
        stream["chroma"] = "≤4:2:2"
    else:
        if pdef and Chroma.YUV444 in pdef.chroma_set:
            stream["chroma"] = "≤4:4:4 (no chroma constraint — profile maximum)"
        elif pdef and Chroma.YUV422 in pdef.chroma_set:
            stream["chroma"] = "≤4:2:2 (profile maximum)"
        else:
            stream["chroma"] = "≤4:2:0 (profile maximum)"

    lbr = all_flags.get("general_lower_bit_rate_constraint", 0)
    if lbr:
        stream["lower_bit_rate"] = ("Yes — bitrate capped at lower sub-tier "
                                     "(~⅔ of level max)")
    else:
        stream["lower_bit_rate"] = "No — full level bitrate available"

    # ── Precision Gate (Byte 2) ──────────────────────────────────
    # For Profile 4+ (RExt/SCC), byte 2 carries an extended constraint
    # layer that further restricts the decoder beyond bytes 0-1.
    # These flags use NEGATIVE CONSTRAINT logic: set = RESTRICT.
    #
    # When byte 2 flags are present, the effective stream capability
    # is the INTERSECTION of byte 0-1 flags and byte 2 flags.
    # The most restrictive constraint wins.
    has_precision_gate = False
    if profile_idc >= 4 and n_actual >= 3:
        em8  = all_flags.get("ext_max_8bit_constraint", 0)
        em10 = all_flags.get("ext_max_10bit_constraint", 0)
        em12 = all_flags.get("ext_max_12bit_constraint", 0)
        em14 = all_flags.get("ext_max_14bit_constraint", 0)
        em422 = all_flags.get("ext_max_422chroma_constraint", 0)
        em420 = all_flags.get("ext_max_420chroma_constraint", 0)
        em_mono = all_flags.get("ext_max_monochrome_constraint", 0)
        e_intra = all_flags.get("ext_intra_only_constraint", 0)

        has_ext_depth = em8 or em10 or em12 or em14
        has_ext_chroma = em_mono or em420 or em422
        has_precision_gate = has_ext_depth or has_ext_chroma or e_intra

        if has_precision_gate:
            # Resolve the EFFECTIVE depth from byte 2 alone
            if em8:
                ext_depth = "≤8-bit"
            elif em10:
                ext_depth = "≤10-bit"
            elif em12:
                ext_depth = "≤12-bit"
            elif em14:
                ext_depth = "≤14-bit"
            else:
                ext_depth = None

            # Resolve the EFFECTIVE chroma from byte 2 alone
            if em_mono:
                ext_chroma = "Monochrome only"
            elif em420:
                ext_chroma = "≤4:2:0"
            elif em422:
                ext_chroma = "≤4:2:2"
            else:
                ext_chroma = None

            # Apply: byte 2 can only TIGHTEN, never loosen
            gate_parts = []
            if ext_depth:
                # Check if byte 2 is tighter than byte 0-1
                depth_order = {"≤8-bit": 0, "≤10-bit": 1, "≤12-bit": 2,
                               "≤14-bit": 3}
                b01_rank = depth_order.get(stream["bit_depth"]
                                           .split(" (")[0], 99)
                b2_rank = depth_order.get(ext_depth, 99)
                if b2_rank < b01_rank or b01_rank == 99:
                    stream["bit_depth"] = (
                        f"{ext_depth} (Precision Gate — Byte 2 constrains "
                        f"beyond Byte 0-1)")
                    gate_parts.append(f"Depth locked to {ext_depth}")
                elif b2_rank == b01_rank:
                    gate_parts.append(f"Depth: {ext_depth} (confirms Byte 0-1)")
                else:
                    gate_parts.append(
                        f"Depth: {ext_depth} (weaker than Byte 0-1 — "
                        f"effective: {stream['bit_depth'].split(' (')[0]})")

            if ext_chroma:
                chroma_order = {"Monochrome only": 0, "≤4:2:0": 1,
                                "≤4:2:2": 2}
                b01_ch_rank = chroma_order.get(stream["chroma"]
                                               .split(" (")[0], 99)
                b2_ch_rank = chroma_order.get(ext_chroma, 99)
                if b2_ch_rank < b01_ch_rank or b01_ch_rank == 99:
                    stream["chroma"] = (
                        f"{ext_chroma} (Precision Gate — Byte 2 constrains "
                        f"beyond Byte 0-1)")
                    gate_parts.append(f"Chroma locked to {ext_chroma}")
                elif b2_ch_rank == b01_ch_rank:
                    gate_parts.append(
                        f"Chroma: {ext_chroma} (confirms Byte 0-1)")
                else:
                    gate_parts.append(
                        f"Chroma: {ext_chroma} (weaker than Byte 0-1 — "
                        f"effective: {stream['chroma'].split(' (')[0]})")

            if e_intra:
                stream["intra_only"] = ("Yes — inter-prediction prohibited "
                                        "(Precision Gate Byte 2)")
                gate_parts.append("Intra-only: no P/B frames")

            stream["precision_gate"] = "; ".join(gate_parts)

    # ── SCC Tool Status (Byte 3, Profile 9-11) ──────────────────
    # For Screen Content Coding profiles, byte 3 flags indicate
    # which SCC-specific tools are DISABLED (negative constraint).
    # Active tools are the profile's key advantage over Main/Main 10.
    if profile_idc in (9, 10, 11) and n_actual >= 4:
        no_pal = all_flags.get("scc_no_palette_constraint", 0)
        no_ibc = all_flags.get("scc_no_ibc_constraint", 0)
        no_act = all_flags.get("scc_no_act_constraint", 0)
        no_sao = all_flags.get("scc_no_sao_constraint", 0)
        no_alf = all_flags.get("scc_no_alf_constraint", 0)

        scc_tools = {}
        scc_tools["palette"] = ("Disabled" if no_pal else
                                "Active — flat-color region coding")
        scc_tools["ibc"] = ("Disabled" if no_ibc else
                            "Active — intra block copy (repeated elements)")
        scc_tools["act"] = ("Disabled" if no_act else
                            "Active — RGB↔YCbCr adaptive color transform")
        if no_sao:
            scc_tools["sao"] = "Disabled — SAO filtering prohibited"
        if no_alf:
            scc_tools["alf"] = "Disabled — ALF prohibited"

        stream["scc_tools"] = scc_tools

    result["stream_info"] = stream

    # Keep legacy content_characteristics for backward compat with tests
    chars = {
        "scan": stream["scan"],
        "frame_only": "Yes" if fo else "No (fields allowed)",
        "max_bit_depth": stream["bit_depth"],
        "max_chroma": stream["chroma"],
        "lower_bit_rate": "Yes" if lbr else "No",
    }
    result["content_characteristics"] = chars

    # RExt sub-profile inference (profile 4, 12, 13 all use RExt constraint flags)
    if profile_idc in (4, 12, 13):
        result["rext_sub_profile"] = _infer_rext_subprofile(all_flags)

    # SCC sub-profile inference (profile 9, 10, 11)
    if profile_idc in (9, 10, 11):
        result["scc_sub_profile"] = _infer_scc_subprofile(
            all_flags, profile_idc)

    # Constraint style detection
    has_any_depth = m8 or m10 or m12 or m14
    has_any_chroma = m_mono or m420 or m422
    if has_any_depth or has_any_chroma or lbr:
        result["constraint_style"] = "Full (depth/chroma flags asserted)"
    else:
        result["constraint_style"] = "Minimal (source flags only, x265/FFmpeg style)"

    # ── RExt Bitrate Multiplier (Profile 4+) ──────────────────────
    # Per ITU-T H.265 Table A.10 (CpbBrVclFactor), RExt profiles
    # use a MULTIPLICATIVE factor: ChromaFactor × BitDepthFactor.
    #
    # The base bitrate (already tier-selected: Main or High) is
    # multiplied by this combined factor.
    #
    # ChromaFactor (from chroma format):
    #   Mono/4:2:0:  1.0×
    #   4:2:2:       1.5×
    #   4:4:4:       2.0×
    #
    # BitDepthFactor (from max bit depth):
    #   ≤10-bit:     1.0×
    #   12-bit:      1.25×
    #   14-bit:      1.5×
    #   ≥16-bit:     2.0×
    #
    # Combined examples (L5.1 Main = 40,000 kbps base):
    #   4:2:0 10-bit: 1.0 × 1.0  = 1.0×  →  40,000 kbps
    #   4:2:2 10-bit: 1.5 × 1.0  = 1.5×  →  60,000 kbps
    #   4:4:4 10-bit: 2.0 × 1.0  = 2.0×  →  80,000 kbps
    #   4:2:0 12-bit: 1.0 × 1.25 = 1.25× →  50,000 kbps
    #   4:2:2 12-bit: 1.5 × 1.25 = 1.875× → 75,000 kbps
    #   4:4:4 12-bit: 2.0 × 1.25 = 2.5×  → 100,000 kbps
    #   4:4:4 16-bit: 2.0 × 2.0  = 4.0×  → 160,000 kbps
    #
    # Note: High Tier base is applied FIRST (e.g. L5.1 High = 160,000),
    # then the factor multiplies that base:
    #   L5.1 High + 4:4:4: 160,000 × 2.0 = 320,000 kbps
    if profile_idc >= 4 and lv:
        eff_depth = stream.get("bit_depth", "").split(" (")[0]
        eff_chroma = stream.get("chroma", "").split(" (")[0]

        # Parse effective bit depth to numeric
        depth_map = {"≤8-bit": 8, "≤10-bit": 10, "≤12-bit": 12,
                     "≤14-bit": 14}
        eff_d = depth_map.get(eff_depth, pdef.max_depth if pdef else 16)

        # ChromaFactor
        if "Mono" in eff_chroma or "4:2:0" in eff_chroma:
            chroma_factor = 1.0
        elif "4:2:2" in eff_chroma:
            chroma_factor = 1.5
        else:
            # 4:4:4 or unconstrained (profile maximum)
            chroma_factor = 2.0

        # BitDepthFactor
        if eff_d <= 10:
            depth_factor = 1.0
        elif eff_d <= 12:
            depth_factor = 1.25
        elif eff_d <= 14:
            depth_factor = 1.5
        else:
            depth_factor = 2.0

        rext_factor = chroma_factor * depth_factor

        if rext_factor > 1.0:
            # Base bitrate already reflects tier (Main or High)
            base_br = result.get("level_max_bitrate", 0)
            rext_br = int(base_br * rext_factor)
            result["level_max_bitrate"] = rext_br
            tier_label = "High" if tier == 1 else "Main"
            # Show the decomposition for transparency
            if chroma_factor > 1.0 and depth_factor > 1.0:
                factor_detail = (
                    f"{chroma_factor:g}× chroma × "
                    f"{depth_factor:g}× depth = "
                    f"{rext_factor:g}×")
            elif chroma_factor > 1.0:
                factor_detail = f"{rext_factor:g}× chroma"
            else:
                factor_detail = f"{rext_factor:g}× depth"
            result["level_max_bitrate_label"] = (
                f"{rext_br:,} kbps ({tier_label} tier × "
                f"{factor_detail} RExt CpbBrVclFactor)")
            result["rext_bitrate_factor"] = rext_factor
            result["rext_chroma_factor"] = chroma_factor
            result["rext_depth_factor"] = depth_factor
            result["rext_bitrate_base"] = base_br

        # Consumer hardware capability warning
        # Most consumer decoders (TVs, STBs, phones) only support
        # Main/Main 10 — they cannot decode RExt streams even if
        # the codec string is technically valid.
        if rext_factor > 1.0 or chroma_factor > 1.0 or depth_factor > 1.0:
            result.setdefault("findings", []).append({
                "severity": "warning",
                "code": "REXT_CONSUMER_UNSUPPORTED",
                "message": (
                    f"RExt stream ({eff_chroma or '4:4:4'}, "
                    f"{eff_depth or '≤' + str(eff_d) + '-bit'}) "
                    f"with {rext_factor:g}× bitrate factor. "
                    f"Consumer hardware (LG C4, Apple TV, Shield TV, "
                    f"phones) only supports Main/Main 10 decoding — "
                    f"this stream will likely fail on consumer devices"),
                "recommendation": (
                    "RExt is intended for professional mezzanine and "
                    "mastering workflows. For consumer delivery, "
                    "transcode to Profile 2 (Main 10) 4:2:0 ≤10-bit"),
            })

    # ── Contextual Validation (Conflict Resolver) ──
    # Analyzes semantic relationships between flags to find
    # contradictions, unexpected configurations, and workflow hints.
    findings = _validate_constraint_context(result)
    if findings:
        existing = result.get("findings", [])
        result["findings"] = findings + existing

    # ── Profile Override Annotation ──
    # When Profile 1/2/3 has impossible constraint claims, the stream_info
    # was built from those flags, but hardware ignores them. Override the
    # display to show the PROFILE truth, not the flag-derived values.
    if result.get("_profile_overrides_constraints"):
        stream = result.get("stream_info", {})
        p_max_d = pdef.max_depth if pdef else 8
        stream["bit_depth"] = (f"≤{p_max_d}-bit "
                                f"(profile-enforced — constraint flags "
                                f"ignored by hardware)")
        stream["chroma"] = ("≤4:2:0 (profile-enforced — constraint flags "
                            "ignored by hardware)")
    # Clean up internal flag
    result.pop("_profile_overrides_constraints", None)

    # ── Verdict ────────────────────────────────────────────────────
    all_findings = result.get("findings", [])
    has_errors = any(f["severity"] == "error" for f in all_findings)
    result["verdict"] = "INVALID" if has_errors else "VALID"

    return result


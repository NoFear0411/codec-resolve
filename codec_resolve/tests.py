"""
Self-test suite: 55 resolve + 43 decode + 17 hybrid + 8 brand + 17 roundtrip = 140 tests.
"""
from .models import Content, Chroma, Transfer, Gamut, Scan, Tier, ConstraintStyle
from .hevc.levels import resolve_hevc_level, resolve_hevc_tier
from .hevc.profiles import resolve_hevc_profile, format_hevc_string
from .hevc.decode import decode_hevc
from .dv.levels import resolve_dv_level
from .dv.profiles import resolve_dv_profile, format_dv_string
from .dv.decode import decode_dv
from .resolve import resolve
from .hybrid import validate_hybrid, decode_hybrid_string, decode_codec_string
from .display import print_results, print_bare, print_hybrid, print_decoded


def self_test() -> bool:
    print("\n--- Self-test ---\n")
    passed = 0
    total = 0

    tests = [
        # === HEVC (MINIMAL constraint style — default) ===
        #
        # MINIMAL: only source characteristic flags (prog/non_packed/frame_only)
        # byte0 for progressive 420: prog=1 non_packed=1 frame_only=1 = 0xB0
        # No byte1 (all zeros → stripped)
        # This matches x265, FFmpeg, and most real-world encoder output.

        # Main profile, 8-bit 4:2:0 SDR 720p
        (Content(1280, 720, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hvc1", "hvc1.1.6.L93.B0",
         "Main 720p SDR → L3.1"),

        # Main profile, 1080p SDR
        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hvc1", "hvc1.1.6.L120.B0",
         "Main 1080p SDR → L4.0"),

        # Main profile, 1080p60
        (Content(1920, 1080, 59.94, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hvc1", "hvc1.1.6.L123.B0",
         "Main 1080p60 → L4.1"),

        # Main 10, 4K HDR10
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "hvc1", "hvc1.2.4.L150.B0",
         "Main 10 4K HDR10 → L5.0"),

        # Main 10, 4K60
        (Content(3840, 2160, 60.0, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "hvc1", "hvc1.2.4.L153.B0",
         "Main 10 4K60 HDR10 → L5.1"),

        # Main 10, High tier (bitrate forces it)
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020,
                 bitrate_kbps=80000),
         "hvc1", "hvc1.2.4.H150.B0",
         "Main 10 4K HDR10 High tier (80Mbps)"),

        # hev1 variant
        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hev1", "hev1.1.6.L120.B0",
         "hev1 variant of Main 1080p"),

        # RExt 4:2:2 10-bit — minimal: just 0xB0 (no depth/chroma assertions)
        (Content(3840, 2160, 23.976, 10, Chroma.YUV422, Transfer.PQ, Gamut.BT2020),
         "hvc1", "hvc1.4.10.L150.B0",
         "RExt 4:2:2 10-bit 4K (minimal)"),

        # RExt 4:4:4 10-bit
        (Content(3840, 2160, 23.976, 10, Chroma.YUV444, Transfer.PQ, Gamut.BT2020),
         "hvc1", "hvc1.4.10.L150.B0",
         "RExt 4:4:4 10-bit 4K (minimal)"),

        # 8K SDR → Level 6.0
        (Content(7680, 4320, 30.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hvc1", "hvc1.1.6.L180.B0",
         "Main 8K30 SDR → L6.0"),

        # HLG 4K
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.HLG, Gamut.BT2020),
         "hvc1", "hvc1.2.4.L150.B0",
         "Main 10 4K HLG → L5.0"),

        # Interlaced 1080i
        # byte0: prog=0 intl=1 non_packed=1 frame_only=0 = 0x60
        (Content(1920, 1080, 29.97, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 scan=Scan.INTERLACED),
         "hvc1", "hvc1.1.6.L120.60",
         "Main 1080i → interlaced flags (minimal)"),

        # RExt Monochrome 10-bit (minimal)
        (Content(1920, 1080, 23.976, 10, Chroma.MONO, Transfer.SDR, Gamut.BT709),
         "hvc1", "hvc1.4.10.L120.B0",
         "RExt Monochrome 10-bit (minimal)"),

        # RExt 12-bit 4:2:0 (minimal)
        (Content(3840, 2160, 23.976, 12, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "hvc1", "hvc1.4.10.L150.B0",
         "RExt 12-bit 4:2:0 4K (minimal)"),

        # === FULL constraint style (now with max_14bit asserted) ===
        # byte1 for FULL: max_420=1(7) + lower_br=1(3) + max_14=1(2) = 0x8C
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020,
                 constraint_style=ConstraintStyle.FULL),
         "hvc1", "hvc1.2.4.L150.BD.8C",
         "Main 10 4K HDR10 (FULL w/ max_14bit)"),

        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 constraint_style=ConstraintStyle.FULL),
         "hvc1", "hvc1.1.6.L120.BF.8C",
         "Main 1080p SDR (FULL w/ max_14bit)"),

        # byte1 for FULL 4:2:2: lower_br=1(3) + max_14=1(2) = 0x0C → "C"
        (Content(3840, 2160, 23.976, 10, Chroma.YUV422, Transfer.PQ, Gamut.BT2020,
                 constraint_style=ConstraintStyle.FULL),
         "hvc1", "hvc1.4.10.L150.BD.C",
         "RExt 4:2:2 10-bit (FULL w/ max_14bit)"),

        (Content(3840, 2160, 23.976, 10, Chroma.YUV444, Transfer.PQ, Gamut.BT2020,
                 constraint_style=ConstraintStyle.FULL),
         "hvc1", "hvc1.4.10.L150.BC.C",
         "RExt 4:4:4 10-bit (FULL w/ max_14bit)"),

        # === ENCODING FLAG AUTO-DETECTION (profiles 3-13) ===

        # --still → Profile 3 Main Still Picture
        (Content(1920, 1080, 1, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 still_image=True),
         "hvc1", "hvc1.3.E.L120.B0.10",
         "Flag --still → Profile 3 MSP"),

        # --intra + 4:4:4 → Profile 5 High Throughput
        (Content(3840, 2160, 23.976, 12, Chroma.YUV444, Transfer.PQ, Gamut.BT2020,
                 intra_only=True),
         "hvc1", "hvc1.5.20.L150.B0",
         "Flag --intra + 444 → Profile 5 HT"),

        # --intra + 4:2:0 8-bit → falls to Profile 1 (no special intra profile)
        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 intra_only=True),
         "hvc1", "hvc1.1.6.L120.B0",
         "Flag --intra + 420 8-bit → Profile 1 (no HT for 420)"),

        # --multiview + 8-bit 4:2:0 → Profile 6 Multiview Main
        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 multiview=True),
         "hvc1", "hvc1.6.46.L120.B0",
         "Flag --multiview + 8-bit 420 → Profile 6"),

        # --multiview + 10-bit 4:2:0 → Profile 13 Multiview RExt
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020,
                 multiview=True),
         "hvc1", "hvc1.13.2010.L150.B0",
         "Flag --multiview + 10-bit → Profile 13 MVRExt"),

        # --scalable + 8-bit 4:2:0 → Profile 7 Scalable Main
        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 scalable=True),
         "hvc1", "hvc1.7.86.L120.B0",
         "Flag --scalable + 8-bit 420 → Profile 7"),

        # --scalable + 10-bit 4:2:0 → Profile 8 Scalable Main 10
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020,
                 scalable=True),
         "hvc1", "hvc1.8.104.L150.B0",
         "Flag --scalable + 10-bit 420 → Profile 8"),

        # --scalable + 4:2:2 → Profile 12 Scalable RExt
        (Content(3840, 2160, 23.976, 10, Chroma.YUV422, Transfer.PQ, Gamut.BT2020,
                 scalable=True),
         "hvc1", "hvc1.12.1010.L150.B0",
         "Flag --scalable + 422 → Profile 12 SRExt"),

        # --scc + 8-bit 4:2:0 → Profile 9 SCC
        (Content(1920, 1080, 60.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 screen_content=True),
         "hvc1", "hvc1.9.202.L123.B0",
         "Flag --scc + 8-bit 420 → Profile 9"),

        # --scc + 10-bit 4:2:0 → Profile 10 SCC 10-bit
        (Content(3840, 2160, 30.0, 10, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 screen_content=True),
         "hvc1", "hvc1.10.404.L150.B0",
         "Flag --scc + 10-bit 420 → Profile 10"),

        # --scc + --intra + 4:4:4 → Profile 11 HT SCC
        (Content(3840, 2160, 60.0, 10, Chroma.YUV444, Transfer.SDR, Gamut.BT709,
                 screen_content=True, intra_only=True),
         "hvc1", "hvc1.11.820.L153.B0",
         "Flag --scc --intra + 444 → Profile 11 HT SCC"),

        # --scc + --intra + 4:2:0 8-bit → Profile 9 (regular SCC suffices)
        (Content(1920, 1080, 60.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 screen_content=True, intra_only=True),
         "hvc1", "hvc1.9.202.L123.B0",
         "Flag --scc --intra + 420 8-bit → Profile 9 (regular SCC)"),

        # --scc + 4:4:4 without --intra → falls to RExt profile 4
        (Content(3840, 2160, 23.976, 10, Chroma.YUV444, Transfer.PQ, Gamut.BT2020,
                 screen_content=True),
         "hvc1", "hvc1.4.10.L150.B0",
         "Flag --scc + 444 (no --intra) → Profile 4 RExt (no non-intra SCC 444)"),

        # === MANUAL OVERRIDE (--hevc-profile still works) ===
        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 hevc_profile=3),
         "hvc1", "hvc1.3.E.L120.B0.10",
         "Override --hevc-profile 3 (still works)"),

        # === NON-STANDARD BIT DEPTHS (auto-detect → RExt profile 4) ===

        # 9-bit 4:2:0 → Main 10 (profile 2 covers 8-10 inclusive per spec)
        (Content(1920, 1080, 23.976, 9, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hvc1", "hvc1.2.4.L120.B0",
         "Main 10 auto: 9-bit 4:2:0 (depth 8-10 inclusive)"),

        # 14-bit 4:2:2 → RExt (auto)
        (Content(3840, 2160, 23.976, 14, Chroma.YUV422, Transfer.PQ, Gamut.BT2020),
         "hvc1", "hvc1.4.10.L150.B0",
         "RExt auto: 14-bit 4:2:2 → profile 4"),

        # 16-bit 4:4:4 → RExt (auto)
        (Content(3840, 2160, 23.976, 16, Chroma.YUV444, Transfer.PQ, Gamut.BT2020),
         "hvc1", "hvc1.4.10.L150.B0",
         "RExt auto: 16-bit 4:4:4 → profile 4"),

        # === DOLBY VISION ===

        # DV Profile 8.1 HDR10-compat, 4K@24
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvh1", "dvh1.08.06",
         "DV 8.1 (HDR10) 4K@24 → Level 06"),

        # DV Profile 8.1 via dvhe
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvhe", "dvhe.08.06",
         "DV 8.1 via dvhe"),

        # DV Profile 8.1 4K60
        (Content(3840, 2160, 60.0, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvh1", "dvh1.08.09",
         "DV 8.1 4K@60 → Level 09"),

        # DV Profile 8.1 1080p
        (Content(1920, 1080, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvh1", "dvh1.08.03",
         "DV 8.1 1080p@24 → Level 03"),

        # DV Profile 8.2 SDR
        (Content(1920, 1080, 23.976, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "dvh1", "dvh1.08.03",
         "DV 8.2 (SDR) 1080p@24 → Level 03"),

        # DV Profile 8.4 HLG
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.HLG, Gamut.BT2020),
         "dvh1", "dvh1.08.06",
         "DV 8.4 (HLG) 4K@24 → Level 06"),

        # DV Profile 5 explicit
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020,
                 dv_profile=5),
         "dvhe", "dvhe.05.06",
         "DV 5 (legacy dual-layer) explicit"),

        # DV P3 gamut
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.P3),
         "dvh1", "dvh1.08.06",
         "DV 8.1 with Display P3 gamut"),

        # DV 720p
        (Content(1280, 720, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvh1", "dvh1.08.01",
         "DV 8.1 720p@24 → Level 01"),

        # DV 8K
        (Content(7680, 4320, 30.0, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvh1", "dvh1.08.12",
         "DV 8.1 8K@30 → Level 12"),

        # === VP9 ===

        # VP9 P0: 8-bit 4:2:0 SDR 1080p → Level 4 (full form)
        (Content(1920, 1080, 30.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "vp09", "vp09.00.40.08.01.01.01.01.00",
         "VP9 P0 1080p30 SDR → L4 (value=40)"),

        # VP9 P0: 720p30 SDR
        (Content(1280, 720, 30.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "vp09", "vp09.00.31.08.01.01.01.01.00",
         "VP9 P0 720p30 SDR → L3.1 (value=31)"),

        # VP9 P2: 4K HDR10 (10-bit 4:2:0 PQ BT.2020)
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "vp09", "vp09.02.50.10.01.09.16.09.00",
         "VP9 P2 4K HDR10 → L5 (value=50)"),

        # VP9 P2: 4K60 HLG
        (Content(3840, 2160, 60.0, 10, Chroma.YUV420, Transfer.HLG, Gamut.BT2020),
         "vp09", "vp09.02.51.10.01.09.18.09.00",
         "VP9 P2 4K60 HLG → L5.1 (value=51)"),

        # VP9 P1: 8-bit 4:4:4
        (Content(1920, 1080, 30.0, 8, Chroma.YUV444, Transfer.SDR, Gamut.BT709),
         "vp09", "vp09.01.40.08.03.01.01.01.00",
         "VP9 P1 1080p 4:4:4 SDR → L4"),

        # VP9 P3: 10-bit 4:2:2 (professional)
        (Content(3840, 2160, 30.0, 10, Chroma.YUV422, Transfer.PQ, Gamut.BT2020),
         "vp09", "vp09.03.50.10.02.09.16.09.00",
         "VP9 P3 4K 4:2:2 HDR → L5"),

        # VP9 P2: 12-bit 4:2:0 (valid but rare)
        (Content(3840, 2160, 30.0, 12, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "vp09", "vp09.02.50.12.01.09.16.09.00",
         "VP9 P2 4K 12-bit → L5"),

        # VP9 P0: 8K30 SDR
        (Content(7680, 4320, 30.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "vp09", "vp09.00.60.08.01.01.01.01.00",
         "VP9 P0 8K30 SDR → L6 (value=60)"),

        # === MULTI-CODEC ===
        # These are tested by calling resolve() with multiple codecs
    ]

    for content, codec, expected, desc in tests:
        total += 1
        try:
            content.validate()
            results = resolve(content, [codec])
            actual = results[0].codec_string
            ok = actual == expected
        except Exception as e:
            actual = f"ERROR: {e}"
            ok = False

        status = "✓" if ok else "✗"
        print(f"  {status} {expected:30s}  ({desc})")
        if not ok:
            print(f"       got: {actual}")
        if ok:
            passed += 1

    # Multi-codec test
    total += 1
    try:
        c = Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020)
        c.validate()
        results = resolve(c, ["hvc1", "dvh1"])
        ok = (results[0].codec_string == "hvc1.2.4.L150.B0" and
              results[1].codec_string == "dvh1.08.06")
        status = "✓" if ok else "✗"
        print(f"  {status} hvc1+dvh1 multi-codec resolve")
        if ok:
            passed += 1
    except Exception as e:
        print(f"  ✗ multi-codec: {e}")

    # Negative: DV rejects 4:2:2
    total += 1
    try:
        c = Content(3840, 2160, 23.976, 10, Chroma.YUV422, Transfer.PQ, Gamut.BT2020)
        c.validate()
        resolve(c, ["dvh1"])
        print(f"  ✗ DV should reject 4:2:2")
    except ValueError:
        print(f"  ✓ DV correctly rejects 4:2:2")
        passed += 1

    print(f"\nResults: {passed}/{total} passed")
    return passed == total


# =============================================================================
# RESOLUTION PRESETS
# =============================================================================

RESOLUTION_PRESETS = {
    "480p": (854, 480), "576p": (1024, 576), "720p": (1280, 720),
    "1080p": (1920, 1080), "1080i": (1920, 1080),
    "1440p": (2560, 1440), "2k": (2048, 1080),
    "4k": (3840, 2160), "uhd": (3840, 2160), "dci4k": (4096, 2160),
    "8k": (7680, 4320), "uhd2": (7680, 4320),
}



def decode_self_test() -> bool:
    """Test the decoder against known codec strings."""
    print("\n--- Decode self-test ---\n")
    passed = 0
    total = 0

    tests = [
        # (codec_string, field_checks: [(key_path, expected), ...])
        ("hvc1.2.4.L150.B0", [
            ("profile_idc", 2),
            ("profile_name", "Main 10"),
            ("tier_name", "Main"),
            ("level_idc", 150),
            ("level_number", 5.0),
            ("constraint_style", "Minimal (source flags only, x265/FFmpeg style)"),
        ]),
        ("hvc1.2.4.L150.BD.88", [
            ("profile_idc", 2),
            ("tier_name", "Main"),
            ("level_number", 5.0),
            ("constraint_style", "Full (depth/chroma flags asserted)"),
        ]),
        ("hvc1.2.4.H150.B0", [
            ("tier", 1),
            ("tier_name", "High"),
        ]),
        ("hvc1.1.6.L120.B0", [
            ("profile_idc", 1),
            ("profile_name", "Main"),
            ("level_number", 4.0),
        ]),
        ("hev1.2.4.L153.B0", [
            ("entry", "hev1"),
            ("profile_idc", 2),
            ("level_number", 5.1),
        ]),
        ("hvc1.4.10.L150.BD.8", [
            ("profile_idc", 4),
            ("profile_name", "Format Range Extensions (RExt)"),
            ("rext_sub_profile", "Main 4:2:2 10"),
        ]),
        ("dvh1.08.06", [
            ("family", "dv"),
            ("profile_idc", 8),
            ("level_id", 6),
            ("level_max_width", 3840),
            ("level_max_height", 2160),
        ]),
        ("dvhe.05.09", [
            ("entry", "dvhe"),
            ("profile_idc", 5),
            ("level_id", 9),
            ("enhancement_layer", True),
            ("status", "Legacy (phased out)"),
            ("colorspace", "IPTPQc2 (proprietary)"),
        ]),
        ("dvh1.08.03", [
            ("profile_idc", 8),
            ("level_id", 3),
            ("level_max_width", 1920),
            ("level_max_height", 1080),
        ]),
        # --- New profile decode tests ---
        ("hvc1.3.E.L120.B0.10", [
            ("profile_idc", 3),
            ("profile_name", "Main Still Picture"),
            ("profile_max_depth", "8-bit"),
            ("profile_note", "Single-frame profile (HEIF, thumbnails)"),
        ]),
        ("hvc1.5.20.L150.B0", [
            ("profile_idc", 5),
            ("profile_name", "High Throughput"),
            ("profile_max_depth", "8-16-bit"),
            ("profile_chroma_support", "4:4:4"),
        ]),
        ("hvc1.6.46.L120.B0", [
            ("profile_idc", 6),
            ("profile_name", "Multiview Main"),
            ("profile_max_depth", "8-bit"),
        ]),
        ("hvc1.9.202.L123.B0", [
            ("profile_idc", 9),
            ("profile_name", "Screen Content Coding (SCC)"),
            ("profile_max_depth", "8-bit"),
        ]),
        ("hvc1.11.820.L153.B0", [
            ("profile_idc", 11),
            ("profile_name", "High Throughput Screen Content Coding"),
            ("profile_max_depth", "8-16-bit"),
            ("profile_chroma_support", "4:4:4"),
        ]),
        ("hvc1.12.1010.L150.B0", [
            ("profile_idc", 12),
            ("profile_name", "Scalable Range Extensions"),
            ("profile_max_depth", "8-16-bit"),
        ]),
        ("hvc1.13.2010.L150.B0", [
            ("profile_idc", 13),
            ("profile_name", "Multiview Range Extensions"),
            ("profile_max_depth", "8-16-bit"),
        ]),
        # Malformed constraint blob (non-dot-separated) — auto-split
        ("hvc1.4.10.H153.B02800000000", [
            ("profile_idc", 4),
            ("tier_name", "High"),
            ("level_number", 5.1),
            ("constraint_bytes_present", 6),
        ]),
        # --- DV Profile decode tests (corrected contracts) ---
        # Profile 9: AVC base
        ("dvav.09.05", [
            ("family", "dv"),
            ("base_layer_codec", "AVC"),
            ("profile_idc", 9),
            ("level_id", 5),
            ("cross_compat", "AVC (H.264) High Profile — 8-bit SDR fallback"),
        ]),
        # Profile 10: AV1 base (NOT HEVC)
        ("dav1.10.09", [
            ("family", "dv"),
            ("base_layer_codec", "AV1"),
            ("profile_idc", 10),
            ("level_id", 9),
            ("cross_compat", "AV1 Main 10 (NOT HEVC)"),
        ]),
        # Profile 20: MV-HEVC spatial
        ("dvh1.20.09", [
            ("family", "dv"),
            ("profile_idc", 20),
            ("level_id", 9),
        ]),
        # Profile 7: Dual-layer with layer detail
        ("dvhe.07.06", [
            ("family", "dv"),
            ("profile_idc", 7),
            ("enhancement_layer", True),
            ("layer_detail", "10-bit BL + 2-bit EL → 12-bit reconstructed"),
        ]),

        # ══ AV1 Decode Tests ═════════════════════════════════════
        # AV1-D1: P0 Main 3.0 8-bit short form
        ("av01.0.04M.08", [
            ("family", "av1"),
            ("seq_profile", 0),
            ("profile_name", "Main"),
            ("seq_level_idx", 4),
            ("level_name", "3.0"),
            ("tier", 0),
            ("bit_depth", 8),
            ("has_optional_fields", False),
            ("verdict", "VALID"),
        ]),
        # AV1-D2: P0 Main 5.1 10-bit short form
        ("av01.0.13M.10", [
            ("family", "av1"),
            ("seq_profile", 0),
            ("level_name", "5.1"),
            ("bit_depth", 10),
            ("verdict", "VALID"),
        ]),
        # AV1-D3: P0 5.1 10-bit full PQ/BT.2020
        ("av01.0.13M.10.0.110.09.16.09.0", [
            ("family", "av1"),
            ("has_optional_fields", True),
            ("color_primaries", 9),
            ("transfer_characteristics", 16),
            ("matrix_coefficients", 9),
            ("video_full_range_flag", 0),
            ("verdict", "VALID"),
        ]),
        # AV1-D4: P0 4.0 8-bit SDR full range
        ("av01.0.08M.08.0.110.01.01.01.1", [
            ("family", "av1"),
            ("level_name", "4.0"),
            ("bit_depth", 8),
            ("video_full_range_flag", 1),
            ("verdict", "VALID"),
        ]),
        # AV1-D5: P1 High 4:4:4
        ("av01.1.13M.10.0.000.09.16.09.0", [
            ("family", "av1"),
            ("seq_profile", 1),
            ("profile_name", "High"),
            ("chroma_name", "4:4:4"),
            ("verdict", "VALID"),
        ]),
        # AV1-D6: P2 Professional 12-bit 4:2:2 High tier
        ("av01.2.13H.12.0.100.09.16.09.0", [
            ("family", "av1"),
            ("seq_profile", 2),
            ("profile_name", "Professional"),
            ("tier", 1),
            ("bit_depth", 12),
            ("verdict", "VALID"),
        ]),
        # AV1-D7: P0 monochrome
        ("av01.0.13M.10.1.111.01.01.01.0", [
            ("family", "av1"),
            ("monochrome", 1),
            ("verdict", "VALID"),
        ]),
        # AV1-D8: Level 31 unconstrained → warning
        ("av01.0.31M.10", [
            ("family", "av1"),
            ("seq_level_idx", 31),
            ("verdict", "VALID"),
        ]),
        # AV1-D9: High tier on L2.1 → ERROR
        ("av01.0.01H.08", [
            ("family", "av1"),
            ("verdict", "INVALID"),
        ]),
        # AV1-D10: P1 + mono=1 → ERROR (P1 forbids mono)
        ("av01.1.13M.10.1.110.09.16.09.0", [
            ("family", "av1"),
            ("verdict", "INVALID"),
        ]),
        # AV1-D11: P0 + 12-bit → ERROR
        ("av01.0.13M.12", [
            ("family", "av1"),
            ("verdict", "INVALID"),
        ]),
        # AV1-D12: AV1 + HDR10+ brand
        ("av01.0.13M.10/cdm4", [
            ("family", "av1"),
            ("seq_profile", 0),
            ("verdict", "VALID"),
        ]),

        # ══ VP9 Decode Tests ═════════════════════════════════════
        # VP9-D1: P0 L3.1 8-bit short form
        ("vp09.00.31.08", [
            ("family", "vp9"),
            ("profile", 0),
            ("profile_name", "Profile 0"),
            ("level_value", 31),
            ("level_name", "3.1"),
            ("bit_depth", 8),
            ("has_optional_fields", False),
            ("verdict", "VALID"),
        ]),
        # VP9-D2: P2 L1.0 10-bit full form PQ/BT.2020 full range
        ("vp09.02.10.10.01.09.16.09.01", [
            ("family", "vp9"),
            ("profile", 2),
            ("profile_name", "Profile 2"),
            ("level_value", 10),
            ("bit_depth", 10),
            ("has_optional_fields", True),
            ("color_primaries", 9),
            ("transfer_characteristics", 16),
            ("matrix_coefficients", 9),
            ("video_full_range_flag", 1),
            ("verdict", "VALID"),
        ]),
        # VP9-D3: P0 L4 8-bit full form SDR
        ("vp09.00.40.08.01.01.01.01.00", [
            ("family", "vp9"),
            ("profile", 0),
            ("level_name", "4"),
            ("bit_depth", 8),
            ("has_optional_fields", True),
            ("color_primaries", 1),
            ("transfer_characteristics", 1),
            ("video_full_range_flag", 0),
            ("verdict", "VALID"),
        ]),
        # VP9-D4: P1 L4.0 8-bit short form (non-4:2:0, short form ok)
        ("vp09.01.40.08", [
            ("family", "vp9"),
            ("profile", 1),
            ("profile_name", "Profile 1"),
            ("has_optional_fields", False),
            ("verdict", "VALID"),
        ]),
        # VP9-D5: P3 L5 10-bit short form
        ("vp09.03.50.10", [
            ("family", "vp9"),
            ("profile", 3),
            ("profile_name", "Profile 3"),
            ("level_name", "5"),
            ("bit_depth", 10),
            ("verdict", "VALID"),
        ]),
        # VP9-D6: P2 12-bit → VALID (with 12-bit rarity warning)
        ("vp09.02.50.12", [
            ("family", "vp9"),
            ("profile", 2),
            ("bit_depth", 12),
            ("verdict", "VALID"),
        ]),
        # VP9-D7: Profile 4 → INVALID (no such profile)
        ("vp09.04.31.08", [
            ("family", "vp9"),
            ("verdict", "INVALID"),
        ]),
        # VP9-D8: P0 + 12-bit → INVALID (P0 only supports {8})
        ("vp09.00.31.12", [
            ("family", "vp9"),
            ("verdict", "INVALID"),
        ]),
        # VP9-D9: 5 fields → INVALID (partial optional fields)
        ("vp09.00.31.08.01", [
            ("family", "vp9"),
            ("verdict", "INVALID"),
        ]),
        # VP9-D10: P1 full form CC=01 (4:2:0) → INVALID (P1 needs CC 02/03)
        ("vp09.01.40.08.01.01.01.01.00", [
            ("family", "vp9"),
            ("verdict", "INVALID"),
        ]),
    ]

    for codec_string, checks in tests:
        total += 1
        try:
            d = decode_codec_string(codec_string)
            all_ok = True
            for key, expected in checks:
                actual = d.get(key)
                if actual != expected:
                    print(f"  ✗ {codec_string}  {key}: "
                          f"expected {expected!r}, got {actual!r}")
                    all_ok = False
                    break
            if all_ok:
                print(f"  ✓ {codec_string}")
                passed += 1
        except Exception as e:
            print(f"  ✗ {codec_string}  ERROR: {e}")

    print(f"\nResults: {passed}/{total} passed")

    # --- Hybrid decode tests ---
    print("\n--- Hybrid decode tests ---\n")
    h_passed = 0
    h_total = 0

    hybrid_tests = [
        # Valid: DV 8 + Main 10
        ("hvc1.2.4.L153.B0, dvh1.08.06", True,
         "Valid DV 8 + Main 10 4K"),

        # ── Level mismatch (Logic Paradox) tests ──────────────────
        # INVALID: HEVC L5.0 (4K frame capacity) + DV L03 (1080p RPU buffer)
        # HEVC decoder can deliver 8.9M pixel frames but DV RPU only
        # has metadata buffers for 2.1M pixels → RPU overflow
        ("hvc1.2.4.L150.B0, dvh1.08.03", False,
         "Level paradox: HEVC L5.0 (4K) + DV L03 (1080p) → RPU overflow"),
        # VALID: HEVC L4.1 (2K frame capacity) + DV L03 (1080p RPU buffer)
        # L4.1 max_luma_ps=2,228,224 fits within DV L03 max 2,073,600 ×1.1
        ("hvc1.2.4.L123.B0, dvh1.08.03", True,
         "Valid: HEVC L4.1 (2K) + DV L03 (1080p) — frame sizes match"),
        # INVALID: HEVC L6.0 (8K frame capacity) + DV L06 (4K RPU buffer)
        ("hvc1.2.4.L180.B0, dvh1.08.06", False,
         "Level paradox: HEVC L6.0 (8K) + DV L06 (4K) → RPU overflow"),

        # ── Base codec mismatch tests ─────────────────────────────
        # Invalid: DV 10 is AV1, NOT HEVC — cannot pair with HEVC base
        ("hvc1.2.4.L150.B0, dvh1.10.06", False,
         "Invalid: DV 10 (AV1) on HEVC base"),
        # Invalid: DV 10 is AV1 — even HEVC Main is wrong base codec
        ("hvc1.1.6.L150.B0, dvh1.10.06", False,
         "Invalid: DV 10 (AV1) on HEVC Main — wrong codec entirely"),
        # Invalid: DV 5 = IPTPQc2 closed-loop — no standard HEVC fallback
        ("hvc1.2.4.L153.B0, dvhe.05.06", True,
         "Valid: DV 5 IPTPQc2 + HEVC Main 10 (correct base for IPT transform)"),
        # Invalid: DV 5 requires Main 10, but base is Profile 1 (8-bit)
        ("hvc1.1.6.L153.B0, dvhe.05.06", False,
         "Invalid: DV 5 requires HEVC Main 10 (Profile 2), not Profile 1"),

        # ── Valid pairings ────────────────────────────────────────
        # Valid: DV 7 dual-layer (BL is Main 10, EL provides +2 bits)
        ("hvc1.2.4.L153.B0, dvhe.07.06", True,
         "Valid: DV 7 dual-layer (BL=Main 10 + EL)"),
        # Valid: DV 8.x with hev1 entry (in-band HEVC)
        ("hev1.2.4.L153.B0, dvhe.08.06", True,
         "Valid: DV 8 + hev1 in-band"),
        # Valid: Standard Netflix 4K combo (L5.0 + DV L06)
        ("hvc1.2.4.L150.B0, dvh1.08.06", True,
         "Valid: HEVC L5.0 (4K) + DV L06 (4K) — levels match"),

        # ── AV1 + DV Hybrid Tests ────────────────────────────────
        # AV1-H1: Valid P10 pair (no brand)
        ("av01.0.13M.10, dav1.10.06", True,
         "Valid: AV1 P0 10-bit + DV P10 (standard streaming pair)"),
        # AV1-H2: Valid P10 + HLG brand
        ("av01.0.13M.10, dav1.10.06/db4h", True,
         "Valid: AV1 + DV P10 + HLG brand"),
        # AV1-H3: Valid P10 + SDR brand
        ("av01.0.13M.10, dav1.10.06/db1p", True,
         "Valid: AV1 + DV P10 + SDR brand"),
        # AV1-H4: 8-bit AV1 + DV P10 → ERROR (needs 10-bit)
        ("av01.0.04M.08, dav1.10.06", False,
         "Invalid: 8-bit AV1 + DV P10 (requires 10-bit)"),
        # AV1-H5: P1 AV1 + DV P10 → ERROR (needs P0)
        ("av01.1.13M.10, dav1.10.06", False,
         "Invalid: AV1 Profile 1 (High) + DV P10 (requires P0 Main)"),
        # AV1-H6: AV1 base + HEVC DV entry → ERROR
        ("av01.0.13M.10, dvh1.08.06", False,
         "Invalid: AV1 base + HEVC DV entry dvh1 (need dav1)"),
    ]

    for hybrid_str, expected_valid, desc in hybrid_tests:
        h_total += 1
        try:
            result = decode_hybrid_string(hybrid_str)
            actual_valid = result["validation"]["valid"]
            if actual_valid == expected_valid:
                print(f"  ✓ {hybrid_str:50s} ({desc})")
                h_passed += 1
            else:
                print(f"  ✗ {hybrid_str:50s} "
                      f"expected valid={expected_valid}, got {actual_valid}")
        except Exception as e:
            print(f"  ✗ {hybrid_str:50s} ERROR: {e}")

    print(f"\nResults: {h_passed}/{h_total} hybrid passed")

    # --- HLS Brand tests (SUPPLEMENTAL-CODECS / RFC 8216bis §4.4.6.2) ---
    print("\n--- HLS Brand tests (SUPPLEMENTAL-CODECS) ---\n")
    b_passed = 0
    b_total = 0

    brand_tests = [
        # (codec_string, expected_brand, expected_compat_id, desc)
        ("dvh1.08.06/db4h", "db4h", 4,
         "DV P8 + HLG brand → compat_id=4"),
        ("dvh1.08.07/db1p", "db1p", 1,
         "DV P8 + HDR10 brand → compat_id=1"),
        ("dvh1.08.06/db2g", "db2g", 2,
         "DV P8 + SDR brand → compat_id=2"),
        ("dvh1.08.06", None, None,
         "DV P8 no brand → no compat inference"),
        ("dav1.10.09/db4h", "db4h", None,
         "DV P10 AV1 + HLG brand (no compat_id for P10)"),
        ("dvh1.08.06/xyz9", "xyz9", None,
         "Unknown brand → stored but no inference"),
        ("hvc1.2.4.L150.B0/cdm4", "cdm4", None,
         "HEVC + HDR10+ brand → stripped and stored"),
    ]

    for codec_str, exp_brand, exp_compat, desc in brand_tests:
        b_total += 1
        try:
            d = decode_codec_string(codec_str)
            brands = d.get("hls_brands", [])
            actual_brand = brands[0]["brand"] if brands else None
            actual_compat = d.get("bl_compat_id")

            # For non-DV (HEVC), bl_compat_id doesn't apply
            if d["family"] == "hevc":
                actual_compat = None

            if actual_brand == exp_brand and actual_compat == exp_compat:
                b_passed += 1
                print(f"  ✓ {codec_str:40s} ({desc})")
            else:
                print(f"  ✗ {codec_str:40s} ({desc})")
                if actual_brand != exp_brand:
                    print(f"      brand: got {actual_brand}, "
                          f"expected {exp_brand}")
                if actual_compat != exp_compat:
                    print(f"      compat_id: got {actual_compat}, "
                          f"expected {exp_compat}")
        except Exception as e:
            print(f"  ✗ {codec_str:40s} ERROR: {e}")

    # Test hybrid decode with brand
    b_total += 1
    try:
        result = decode_hybrid_string(
            "hvc1.2.4.L150.B0, dvh1.08.06/db4h")
        dv = result["dv"]
        val = result["validation"]
        if (dv.get("bl_compat_id") == 4
                and dv.get("hls_brands", [{}])[0].get("brand") == "db4h"
                and val["valid"]):
            b_passed += 1
            print(f"  ✓ {'hybrid + brand':40s} "
                  f"(hvc1+dvh1/db4h → valid, compat_id=4)")
        else:
            print(f"  ✗ {'hybrid + brand':40s}")
    except Exception as e:
        print(f"  ✗ {'hybrid + brand':40s} ERROR: {e}")

    print(f"\nResults: {b_passed}/{b_total} brand passed")

    # --- Roundtrip tests: resolve → decode → verify fields match ---
    print("\n--- Roundtrip tests (resolve → decode → verify) ---\n")
    rt_passed = 0
    rt_total = 0

    roundtrip_tests = [
        # (content, codec, desc)
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "hvc1", "Main 10 4K PQ → L5.0"),
        (Content(1920, 1080, 59.94, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hvc1", "Main 1080p60 → L4.1"),
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020,
                 bitrate_kbps=80000),
         "hvc1", "Main 10 4K High tier"),
        (Content(3840, 2160, 23.976, 10, Chroma.YUV422, Transfer.PQ, Gamut.BT2020),
         "hvc1", "RExt 4:2:2 10-bit"),
        (Content(1920, 1080, 29.97, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709,
                 scan=Scan.INTERLACED),
         "hvc1", "1080i interlaced"),
        (Content(3840, 2160, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020,
                 constraint_style=ConstraintStyle.FULL),
         "hvc1", "FULL constraint bytes"),
        (Content(7680, 4320, 30.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "hvc1", "8K SDR → L6.0"),
        (Content(1280, 720, 23.976, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvh1", "DV 8.1 720p"),
        (Content(3840, 2160, 60.0, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "dvh1", "DV 8.1 4K60"),

        # ── AV1 Roundtrip Tests ──────────────────────────────────
        # AV1-R1: 4K30 10-bit PQ/BT.2020
        (Content(3840, 2160, 30.0, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "av01", "AV1 Main 4K30 PQ → L5.0"),
        # AV1-R2: 1080p60 8-bit SDR/BT.709
        (Content(1920, 1080, 60.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "av01", "AV1 Main 1080p60 SDR → L4.1"),
        # AV1-R3: 8K30 10-bit PQ → level ≥ 6.0
        (Content(7680, 4320, 30.0, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "av01", "AV1 Main 8K30 PQ → L6.0"),
        # AV1-R4: 4K60 12-bit 4:2:2 P2
        (Content(3840, 2160, 60.0, 12, Chroma.YUV422, Transfer.PQ, Gamut.BT2020),
         "av01", "AV1 Professional 4K60 12-bit 4:2:2"),

        # ── VP9 Roundtrip Tests ─────────────────────────────────
        # VP9-R1: 1080p30 8-bit SDR
        (Content(1920, 1080, 30.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "vp09", "VP9 P0 1080p30 SDR → L4"),
        # VP9-R2: 4K30 10-bit HDR10
        (Content(3840, 2160, 30.0, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020),
         "vp09", "VP9 P2 4K30 HDR10 → L5"),
        # VP9-R3: 8K30 8-bit SDR
        (Content(7680, 4320, 30.0, 8, Chroma.YUV420, Transfer.SDR, Gamut.BT709),
         "vp09", "VP9 P0 8K30 SDR → L6"),
        # VP9-R4: 4K 10-bit 4:2:2 (Profile 3)
        (Content(3840, 2160, 30.0, 10, Chroma.YUV422, Transfer.PQ, Gamut.BT2020),
         "vp09", "VP9 P3 4K 4:2:2 HDR"),
    ]

    for content, codec, desc in roundtrip_tests:
        rt_total += 1
        try:
            content.validate()
            resolved = resolve(content, [codec])[0]
            decoded = decode_codec_string(resolved.codec_string)

            issues = []

            if resolved.family == "hevc":
                # Verify profile roundtrips
                r_pidc = None
                if "profile " in resolved.profile_name:
                    try:
                        r_pidc = int(resolved.profile_name.split("profile ")[1]
                                     .rstrip(")"))
                    except (ValueError, IndexError):
                        pass
                d_pidc = decoded["profile_idc"]
                if r_pidc and r_pidc != d_pidc:
                    issues.append(f"profile: {r_pidc}→{d_pidc}")

                # Verify tier roundtrips
                if resolved.tier_name != decoded["tier_name"]:
                    issues.append(
                        f"tier: {resolved.tier_name}→{decoded['tier_name']}")

                # Verify level roundtrips
                r_lvl = float(resolved.level_name.split("Level ")[1]
                              .split(" ")[0])
                d_lvl = decoded["level_number"]
                if r_lvl != d_lvl:
                    issues.append(f"level: {r_lvl}→{d_lvl}")

            elif resolved.family == "dv":
                # Verify DV profile roundtrips
                d_pidc = decoded["profile_idc"]
                r_pidc = int(resolved.codec_string.split(".")[1])
                if r_pidc != d_pidc:
                    issues.append(f"dv_profile: {r_pidc}→{d_pidc}")

                # Verify DV level roundtrips
                d_lvl = decoded["level_id"]
                r_lvl = int(resolved.codec_string.split(".")[2])
                if r_lvl != d_lvl:
                    issues.append(f"dv_level: {r_lvl}→{d_lvl}")

            elif resolved.family == "av1":
                # Verify AV1 profile roundtrips
                if decoded["seq_profile"] != int(resolved.codec_string.split(".")[1]):
                    issues.append(
                        f"av1_profile: {resolved.codec_string.split('.')[1]}"
                        f"→{decoded['seq_profile']}")

                # Verify level roundtrips
                r_level_idx = int(resolved.codec_string.split(".")[2][:2])
                if decoded["seq_level_idx"] != r_level_idx:
                    issues.append(
                        f"av1_level: idx {r_level_idx}→{decoded['seq_level_idx']}")

                # Verify tier roundtrips
                r_tier_char = resolved.codec_string.split(".")[2][2]
                d_tier = "M" if decoded["tier"] == 0 else "H"
                if r_tier_char != d_tier:
                    issues.append(f"av1_tier: {r_tier_char}→{d_tier}")

                # Verify bit depth roundtrips
                r_depth = int(resolved.codec_string.split(".")[3])
                if decoded["bit_depth"] != r_depth:
                    issues.append(f"av1_depth: {r_depth}→{decoded['bit_depth']}")

                # Verify decoded verdict is VALID
                if decoded.get("verdict") != "VALID":
                    issues.append(f"verdict: {decoded.get('verdict')}")

            elif resolved.family == "vp9":
                # Verify VP9 profile roundtrips
                r_profile = int(resolved.codec_string.split(".")[1])
                if decoded["profile"] != r_profile:
                    issues.append(
                        f"vp9_profile: {r_profile}→{decoded['profile']}")

                # Verify level roundtrips
                r_level = int(resolved.codec_string.split(".")[2])
                if decoded["level_value"] != r_level:
                    issues.append(
                        f"vp9_level: {r_level}→{decoded['level_value']}")

                # Verify bit depth roundtrips
                r_depth = int(resolved.codec_string.split(".")[3])
                if decoded["bit_depth"] != r_depth:
                    issues.append(
                        f"vp9_depth: {r_depth}→{decoded['bit_depth']}")

                # Verify decoded verdict is VALID
                if decoded.get("verdict") != "VALID":
                    issues.append(f"verdict: {decoded.get('verdict')}")

            if issues:
                print(f"  ✗ {resolved.codec_string:30s} ({desc}) — {issues}")
            else:
                print(f"  ✓ {resolved.codec_string:30s} ({desc})")
                rt_passed += 1
        except Exception as e:
            print(f"  ✗ ({desc}) ERROR: {e}")

    print(f"\nResults: {rt_passed}/{rt_total} roundtrip passed")
    return (passed == total and h_passed == h_total
            and b_passed == b_total and rt_passed == rt_total)


# =============================================================================
# CLI
# =============================================================================


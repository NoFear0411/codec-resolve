"""
CLI entry point for codec_resolve.

Usage: python -m codec_resolve [options]
"""
import sys
import argparse
from .models import Content, Chroma, Transfer, Gamut, Scan, Tier, ConstraintStyle
from .resolve import resolve
from .hybrid import decode_hybrid_string, decode_codec_string
from .hevc.decode import decode_hevc
from .dv.decode import decode_dv
from .display import print_results, print_bare, print_hybrid, print_decoded
from .tests import self_test, decode_self_test

RESOLUTION_PRESETS = {
    "720p": (1280, 720), "hd": (1280, 720),
    "1080p": (1920, 1080), "fhd": (1920, 1080), "2k": (1920, 1080),
    "1440p": (2560, 1440), "qhd": (2560, 1440),
    "4k": (3840, 2160), "uhd": (3840, 2160), "2160p": (3840, 2160),
    "8k": (7680, 4320), "4320p": (7680, 4320),
}


def parse_resolution(s):
    s_lower = s.lower().strip()
    if s_lower in RESOLUTION_PRESETS:
        return RESOLUTION_PRESETS[s_lower]
    for sep in ["x", "×", "X", "*"]:
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    raise ValueError(f"Cannot parse resolution: '{s}'. Use WxH or: "
                     f"{', '.join(sorted(RESOLUTION_PRESETS.keys()))}")


def parse_codecs(s):
    families = [f.strip().lower() for f in s.split(",")]
    valid = {"hvc1", "hev1", "dvhe", "dvh1", "dvav", "dva1", "dav1", "av01"}
    aliases = {
        "hevc": ["hvc1", "hev1"],
        "av1": ["av01"],
        "dv": ["dvhe", "dvh1"],
        "dv-avc": ["dvav", "dva1"],
        "dv-av1": ["dav1"],
        "all": ["hvc1", "hev1", "av01", "dvhe", "dvh1"],
    }
    result = []
    for f in families:
        if f in valid:
            result.append(f)
        elif f in aliases:
            result.extend(aliases[f])
        else:
            raise ValueError(f"Unknown codec: '{f}'. "
                             f"Valid: {', '.join(sorted(valid | set(aliases.keys())))}")
    return list(dict.fromkeys(result))


# =============================================================================
# CODEC STRING DECODER (reverse resolver)
#
# Feed it a codec string → get back all decoded parameters.
# Handles:
#   HEVC:          hvc1, hev1
#   Dolby Vision:  dvhe, dvh1 (HEVC base)
#                  dvav, dva1 (AVC base)
#                  dav1       (AV1 base)
# =============================================================================



HELP_TEXT = """
┌─────────────────────────────────────────────────────────────────┐
│  HEVC + Dolby Vision Codec String Resolver & Validator          │
│  5,216 lines · 88 tests · zero dependencies                    │
│  Bidirectional: resolve ↔ decode ↔ validate ↔ hybrid            │
└─────────────────────────────────────────────────────────────────┘

─── RESOLVE (forward: content → codec string) ─────────────────────

 REQUIRED    FLAG        VALUES
 ──────────  ──────────  ────────────────────────────────────
 codec       --codec     hvc1 hev1 dvhe dvh1 │ hevc dv all
                         dvav dva1 dav1 │ dv-avc dv-av1
 resolution  -r          3840x2160 │ 4k 1080p 720p 8k ...
 framerate   --fps       23.976  29.97  59.94  60  120
 bit depth   -d          8-16 (integer, all values for RExt)
 chroma      -c          420  422  444  mono
 transfer    -t          sdr  pq  hlg
 gamut       -g          bt709  bt2020  p3

 OPTIONAL    FLAG               EFFECT
 ──────────  ─────────────────  ──────────────────────────────
 compat      --compat MODE      DV fallback: hdr10|sdr|hlg|none
 bitrate     --bitrate KBPS     HEVC Main↔High tier selection
 scan        --scan interlaced  Interlaced source flags
 tier        --tier high        Force HEVC High tier
 constraints --constraints full  Assert all depth/chroma flags
 bare output --bare              Just codec strings, no labels

 ENCODING FLAGS (auto-select specialized HEVC profiles):
   --still        Single frame / still image       → Profile 3
   --intra        All-intra, no inter-prediction   → Profile 5, 11
   --scc          Screen content (IBC + palette)   → Profile 9, 10, 11
   --scalable     SHVC multi-layer                 → Profile 7, 8, 12
   --multiview    Stereo 3D / multi-camera         → Profile 6, 13

 MANUAL OVERRIDES (bypass auto-detection):
   --hevc-profile N    Force HEVC profile (1-13)
   --dv-profile N      Force DV profile (5/7/8/9/10/20)
   --compat MODE       Force DV compatibility (hdr10/sdr/hlg/none)

─── DECODE + VALIDATE (reverse: codec string → analysis) ──────────

 The --decode flag runs three stages:
   1. PARSE:     Extract all fields from the codec string
   2. DECODE:    Map fields to human-readable spec definitions
   3. VALIDATE:  14 semantic checks on constraint flag combinations

 Accepts four input formats:
   HEVC standalone:    %(prog)s --decode hvc1.2.4.L153.B0
   DV triplet:         %(prog)s --decode dvh1.08.06
   DV unified format:  %(prog)s --decode dvh1.08.06.H153.B0.00.00.00.00.00
   Hybrid pair:        %(prog)s --decode "hvc1.2.4.L153.B0, dvh1.08.06"

 Unified DV format auto-reconstructs the HEVC base layer via MPEG-4
 Part 15 entry mapping (dvh1→hev1, dvhe→hvc1), infers the HEVC
 profile from the DV compatibility table, and runs full cross-
 validation. Embedded HEVC errors propagate into the hybrid verdict.

 Decode examples:
   # HEVC with RExt constraint bytes
   %(prog)s --decode hvc1.4.10.H153.B0.28
     → ⚠ HIGH_TIER_LBR: High Tier + bitrate cap contradicts
     → ⚠ INBLD_SET: Dependent layer flag on standalone profile

   # Compat flag cross-reference
   %(prog)s --decode hvc1.4.2.L153.B0
     → ✗ COMPAT_SELF_BIT_MISSING: Profile 4 self-bit not set
     → ✗ COMPAT_BITS_INCOMPLETE: Missing required compat bits

   # Tier/level pairing
   %(prog)s --decode hvc1.2.4.H90.B0
     → ✗ TIER_INVALID_FOR_LEVEL: Level 3.0 has no High Tier

   # DV unified format (embedded HEVC + cross-validation)
   %(prog)s --decode dvh1.08.06.H153.B0.00.00.00.00.00
     → Auto-reconstructed HEVC: hev1.2.4.H153.B0.00.00.00.00.00
     → ✓ Profile match + ⚠ consumer tier warning

   # All DV profiles
   %(prog)s --decode dvh1.08.06          # P8: HEVC streaming (dominant)
   %(prog)s --decode dvhe.05.09          # P5: IPTPQc2 closed-loop
   %(prog)s --decode dvhe.07.06          # P7: Blu-ray dual-layer
   %(prog)s --decode dvav.09.05          # P9: AVC legacy
   %(prog)s --decode dav1.10.09          # P10: AV1 (NOT HEVC)
   %(prog)s --decode dvh1.20.09          # P20: MV-HEVC / Vision Pro

   # Cross-validate HLS hybrid pair
   %(prog)s --decode "hvc1.2.4.L153.B0, dvh1.08.06"
   %(prog)s --decode hvc1.2.4.L153.B0 dvh1.08.06  (auto-detects pair)

─── HEVC PROFILES (all 13, ITU-T H.265 Annex A) ──────────────────

   IDC  Name                       Depth   Chroma        Auto-selected when
   ───  ─────────────────────────  ──────  ────────────  ──────────────────────
    1   Main                       8       4:2:0         (default for 8-bit 420)
    2   Main 10                    8-10    4:2:0         (default for ≤10-bit 420)
    3   Main Still Picture         8       4:2:0         --still
    4   Range Extensions (RExt)    8-16    all + mono    (fallback for >10-bit or non-420)
    5   High Throughput            8-16    4:4:4         --intra + (444 or >10-bit)
    6   Multiview Main             8       4:2:0         --multiview + 8-bit 420
    7   Scalable Main              8       4:2:0         --scalable + 8-bit 420
    8   Scalable Main 10           8-10    4:2:0         --scalable + ≤10-bit 420
    9   Screen Content Coding      8       4:2:0         --scc + 8-bit 420
   10   Screen Content Coding 10   8-10    4:2:0         --scc + ≤10-bit 420
   11   High Throughput SCC        8-16    4:4:4         --scc --intra + (444 or >10-bit)
   12   Scalable Range Ext         8-16    all + mono    --scalable + (>10-bit or non-420)
   13   Multiview Range Ext        8-16    all + mono    --multiview + (>10-bit or non-420)

   "8-16 bit" = every integer: 8, 9, 10, 11, 12, 13, 14, 15, 16

─── DV PROFILES (ETSI TS 103 572 / Dolby CMS) ────────────────────

   Prof  Entry       Base Codec        Layers       Fallback
   ────  ──────────  ────────────────  ───────────  ──────────────────────────
    5    dvhe        HEVC (IPTPQc2)    BL+EL+RPU   NONE (closed-loop)
    7    dvhe/dvh1   HEVC Main 10      BL+EL+RPU   HDR10 (BL only, 10-bit)
    8.1  dvhe/dvh1   HEVC Main 10      BL+RPU       HDR10 (PQ+BT.2020) ★ dominant
    8.2  dvhe/dvh1   HEVC Main 10      BL+RPU       SDR (BT.709)
    8.4  dvhe/dvh1   HEVC Main 10      BL+RPU       HLG (BT.2020, Apple/broadcast)
    9    dvav/dva1   AVC High          BL+RPU       SDR (8-bit AVC)
   10    dav1        AV1 Main 10       BL+RPU       HDR10 (AV1 PQ) — NOT HEVC
   20    dvh1        MV-HEVC           BL+RPU       2D HEVC Main 10 (single-eye)

   Metadata delivery:
     dvh1/dva1/dav1 = out-of-band (sample description — HLS/MP4)
     dvhe/dvav      = in-band (NAL units — DASH/TS)

   ⚠ Profile 5 uses proprietary IPTPQc2 colorspace. Standard HEVC decoders
     will produce green/purple distortion. No standard HDR/SDR fallback.
   ⚠ Profile 10 is AV1-based. Cannot be paired with HEVC base layer.
   ⚠ Profile 20 requires MV-HEVC (multiview) decoder for stereoscopic.

─── VALIDATION CODES ──────────────────────────────────────────────

 HEVC standalone (14 semantic checks):

   Severity   Code                         What it catches
   ─────────  ───────────────────────────  ─────────────────────────────────
   ✗ error    TIER_INVALID_FOR_LEVEL       High Tier on Level < 4.0
   ✗ error    FRAME_ONLY_INTERLACED        frame_only + interlaced (exclusive)
   ✗ error    DEPTH_CASCADE_BROKEN         max_8bit=1 but max_10bit=0
   ✗ error    CHROMA_CASCADE_BROKEN        max_420=1 but max_422=0
   ✗ error    COMPAT_SELF_BIT_MISSING      Profile self-bit not in compat flags
   ✗ error    COMPAT_BITS_INCOMPLETE       Required compat bits missing
   ✗ error    RESERVED_BYTE_NONZERO        Non-zero reserved byte (P1-3)
   ✗ error    PRECISION_GATE_*_CASCADE     Byte 2 ext flags violate cascade
   ⚠ warning  HIGH_TIER_LBR               High Tier + lower bitrate cap
   ⚠ warning  INBLD_SET                    Dependent layer flag on standalone
   ⚠ warning  ONE_PICTURE_ONLY             Single-frame flag on video
   ⚠ warning  COMPAT_BITS_EXTRA            Extra bits outside profile set
   ⚠ warning  LEVEL_UNKNOWN                Non-standard level_idc
   ⚠ warning  PROFILE_CONSTRAINT_IMPOSSIBLE Flags exceed profile capability
   ⚠ warning  REXT_CONSUMER_UNSUPPORTED    RExt on consumer hardware
   ⚠ warning  SCC_ALL_TOOLS_DISABLED       All SCC tools off → base profile
   ⚠ warning  INTRA_ONLY_CONSTRAINT        No P/B frames allowed
   ℹ info     SCAN_UNKNOWN                 Neither progressive nor interlaced
   ℹ info     REXT_WORKFLOW                Mastering/streaming/dependent
   ℹ info     REXT_EXCESSIVE_PROFILE       RExt constrained to P1/P2 range
   ℹ info     SCC_TOOLS_ACTIVE             SCC tool status summary

 Hybrid cross-validation (22 checks):

   ✗ error    Base codec / profile / depth / level / INBLD mismatch
   ⚠ warning  Consumer tier / entry sync / EL unverifiable / spurious INBLD
   ℹ info     RPU overhead ceiling / throughput / tier bottleneck notes

─── TESTING ───────────────────────────────────────────────────────

 %(prog)s --test                  47 forward-resolve tests
 %(prog)s --decode-test           21 decode + 11 hybrid + 9 roundtrip tests

─── EXAMPLES ──────────────────────────────────────────────────────

 # 4K HDR10 Dolby Vision — the Netflix/Apple TV+ standard
 %(prog)s --codec dvh1 -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020
 → dvh1.08.06

 # Same content, HEVC string
 %(prog)s --codec hvc1 -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020
 → hvc1.2.4.L150.B0

 # Both at once → hybrid string for HLS manifest
 %(prog)s --codec hvc1,dvh1 -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020
 → hvc1.2.4.L150.B0, dvh1.08.06

 # Explicit HDR10 compatibility
 %(prog)s --codec hvc1,dvh1 -r 4k --fps 24 -d 10 -c 420 -t pq -g bt2020 --compat hdr10
 → hvc1.2.4.L150.B0, dvh1.08.06

 # PQ content with HLG compatibility override
 %(prog)s --codec hvc1,dvh1 -r 4k --fps 24 -d 10 -c 420 -t pq -g bt2020 --compat hlg
 → hvc1.2.4.L150.B0, dvh1.08.06  (Profile 8.4 despite PQ transfer)

 # 1080p SDR — basic streaming
 %(prog)s --codec all -r 1080p --fps 23.976 -d 8 -c 420 -t sdr -g bt709

 # 4K60 HDR10 — high framerate sport
 %(prog)s --codec all -r 4k --fps 59.94 -d 10 -c 420 -t pq -g bt2020

 # 4K HLG broadcast (Apple / broadcast standard)
 %(prog)s --codec hvc1,dvh1 -r 4k --fps 29.97 -d 10 -c 420 -t hlg -g bt2020

 # DASH delivery (in-band entries)
 %(prog)s --codec hev1,dvhe -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020

 # 4K 4:2:2 10-bit — professional (HEVC RExt, no DV)
 %(prog)s --codec hvc1 -r 4k --fps 23.976 -d 10 -c 422 -t pq -g bt2020

 # High bitrate → forces HEVC High tier
 %(prog)s --codec hvc1 -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020 --bitrate 80000
 → hvc1.2.4.H150.B0

 # Legacy DV Profile 5 (IPTPQc2 closed-loop, no standard fallback)
 %(prog)s --codec dvhe -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020 --dv-profile 5
 → dvhe.05.06

 # DV Profile 7 Blu-ray (dual-layer BL+EL → 12-bit)
 %(prog)s --codec dvhe -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020 --dv-profile 7
 → dvhe.07.06

 # Full constraint bytes (BD.88 style instead of B0)
 %(prog)s --codec hvc1 -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020 --constraints full
 → hvc1.2.4.L150.BD.88

 # Bare output for scripting / piping
 %(prog)s --codec all -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020 --bare

 # 1080i interlaced
 %(prog)s --codec hvc1 -r 1080p --fps 29.97 -d 8 -c 420 -t sdr -g bt709 --scan interlaced

 # Screen Content Coding (auto → profile 9)
 %(prog)s --codec hvc1 -r 1080p --fps 60 -d 8 -c 420 -t sdr -g bt709 --scc

 # High Throughput 4:4:4 (auto → profile 5)
 %(prog)s --codec hvc1 -r 4k --fps 23.976 -d 12 -c 444 -t pq -g bt2020 --intra

 # Scalable Main 10 (auto → profile 8)
 %(prog)s --codec hvc1 -r 4k --fps 23.976 -d 10 -c 420 -t pq -g bt2020 --scalable

 # Multiview Main (auto → profile 6)
 %(prog)s --codec hvc1 -r 1080p --fps 23.976 -d 8 -c 420 -t sdr -g bt709 --multiview

 # HT SCC 4:4:4 (auto → profile 11)
 %(prog)s --codec hvc1 -r 4k --fps 60 -d 10 -c 444 -t sdr -g bt709 --intra --scc

 # Still image (auto → profile 3) — HEIF
 %(prog)s --codec hvc1 -r 4k --fps 1 -d 8 -c 420 -t sdr -g bt709 --still

 # 14-bit RExt (auto → profile 4)
 %(prog)s --codec hvc1 -r 4k --fps 23.976 -d 14 -c 422 -t pq -g bt2020
"""


def main():
    parser = argparse.ArgumentParser(
        prog="codec_resolve",
        description="HEVC + Dolby Vision codec string resolver & validator. "
                    "Bidirectional: resolve ↔ decode ↔ validate ↔ hybrid.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_TEXT)

    # Handle early-exit flags before requiring other args
    if "--test" in sys.argv:
        success = self_test()
        sys.exit(0 if success else 1)
    if "--decode-test" in sys.argv:
        success = decode_self_test()
        sys.exit(0 if success else 1)
    if "--decode" in sys.argv:
        idx = sys.argv.index("--decode")
        strings = sys.argv[idx + 1:]
        if not strings:
            print("Error: --decode requires at least one codec string",
                  file=sys.stderr)
            sys.exit(1)

        # Rejoin args and split on comma to detect hybrid strings
        # "hvc1.2.4.L153.B0, dvh1.08.06" → hybrid
        # "hvc1.2.4.L153.B0 dvh1.08.06"  → separate decode (legacy)
        joined = " ".join(strings)

        # If commas present, treat as a single hybrid string
        if "," in joined:
            try:
                result = decode_hybrid_string(joined)
                print_hybrid(result)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Check if we have exactly one HEVC + one DV → auto-hybrid
            entries = [s.split(".")[0].lower() for s in strings]
            hevc_entries = [s for s, e in zip(strings, entries)
                           if e in ("hvc1", "hev1")]
            dv_entries = [s for s, e in zip(strings, entries)
                         if e in ("dvhe", "dvh1", "dva1", "dvav", "dav1")]

            if len(hevc_entries) == 1 and len(dv_entries) == 1:
                # Auto-detect hybrid pair
                try:
                    hybrid = f"{hevc_entries[0]}, {dv_entries[0]}"
                    result = decode_hybrid_string(hybrid)
                    print_hybrid(result)
                except ValueError as e:
                    print(f"Error: {e}", file=sys.stderr)
                    sys.exit(1)
            else:
                # Individual decodes
                ok = True
                for s in strings:
                    try:
                        d = decode_codec_string(s)
                        print_decoded(d)
                    except ValueError as e:
                        print(f"Error: {e}", file=sys.stderr)
                        ok = False
                sys.exit(0 if ok else 1)
        sys.exit(0)

    req = parser.add_argument_group("Content (all required)")
    req.add_argument("--codec", required=True,
                     help="hvc1,hev1,dvhe,dvh1,dvav,dva1,dav1 | hevc,dv,dv-avc,dv-av1,all")
    req.add_argument("-r", "--resolution", required=True, metavar="WxH",
                     help="3840x2160 | 4k,1080p,720p,8k...")
    req.add_argument("--fps", required=True, type=float,
                     help="23.976, 29.97, 59.94, 60...")
    req.add_argument("-d", "--depth", required=True, type=int,
                     help="Bit depth (8-16, integer)")
    req.add_argument("-c", "--chroma", required=True,
                     choices=["mono", "420", "422", "444"])
    req.add_argument("-t", "--transfer", required=True,
                     help="sdr | pq | hlg")
    req.add_argument("-g", "--gamut", required=True,
                     help="bt709 | bt2020 | p3")

    opt = parser.add_argument_group("Optional")
    opt.add_argument("--bitrate", type=int, metavar="KBPS",
                     help="For HEVC tier selection (Main vs High)")
    opt.add_argument("--scan", choices=["progressive", "interlaced"],
                     default="progressive")
    opt.add_argument("--tier", choices=["main", "high"],
                     help="Force HEVC tier")
    opt.add_argument("--constraints", choices=["minimal", "full"],
                     default="minimal",
                     help="HEVC constraint bytes (default: minimal)")

    enc = parser.add_argument_group("Encoding characteristics (auto-select profiles 3-13)")
    enc.add_argument("--still", action="store_true",
                     help="Still image / single frame (→ Profile 3)")
    enc.add_argument("--intra", action="store_true",
                     help="All-intra encoding, no inter-prediction (→ Profile 5, 11)")
    enc.add_argument("--scc", action="store_true",
                     help="Screen content: IBC + palette mode (→ Profile 9, 10, 11)")
    enc.add_argument("--scalable", action="store_true",
                     help="SHVC multi-layer scalability (→ Profile 7, 8, 12)")
    enc.add_argument("--multiview", action="store_true",
                     help="Stereo 3D / multi-camera views (→ Profile 6, 13)")

    ovr = parser.add_argument_group("Manual overrides (bypass auto-detection)")
    ovr.add_argument("--hevc-profile", type=int, metavar="N",
                     choices=list(range(1, 14)),
                     help="Force HEVC profile (1-13)")
    ovr.add_argument("--dv-profile", type=int, choices=[5, 7, 8, 9, 10, 20],
                     metavar="N", help="Force DV profile (5/7/8/9/10/20)")
    ovr.add_argument("--compat", type=str,
                     choices=["hdr10", "sdr", "hlg", "none"],
                     metavar="MODE",
                     help="DV base layer compatibility: hdr10 | sdr | hlg | none")
    ovr.add_argument("--dv-bl-compat", type=int, choices=[0, 1, 2, 4],
                     metavar="ID",
                     help="Raw bl_signal_compatibility_id (0/1/2/4). "
                          "Prefer --compat for human-readable input")

    out = parser.add_argument_group("Output")
    out.add_argument("--bare", action="store_true",
                     help="Just codec strings, no labels")

    args = parser.parse_args()

    # Parse inputs
    codecs = parse_codecs(args.codec)
    w, h = parse_resolution(args.resolution)
    scan = Scan.INTERLACED if args.scan == "interlaced" else Scan.PROGRESSIVE
    tier = None
    if args.tier == "main":
        tier = Tier.MAIN
    elif args.tier == "high":
        tier = Tier.HIGH

    # Resolve --compat (human-readable) → bl_compat_id (numeric)
    # --compat takes priority over --dv-bl-compat if both specified
    compat_map = {"hdr10": 1, "sdr": 2, "hlg": 4, "none": 0}
    bl_compat = None
    if args.compat is not None:
        bl_compat = compat_map[args.compat]
    elif args.dv_bl_compat is not None:
        bl_compat = args.dv_bl_compat

    content = Content(
        width=w, height=h, fps=args.fps,
        bit_depth=args.depth,
        chroma=Chroma.parse(args.chroma),
        transfer=Transfer.parse(args.transfer),
        gamut=Gamut.parse(args.gamut),
        bitrate_kbps=args.bitrate,
        scan=scan,
        tier=tier,
        dv_profile=args.dv_profile,
        dv_bl_compat_id=bl_compat,
        hevc_profile=args.hevc_profile,
        constraint_style=ConstraintStyle.FULL if args.constraints == "full"
                         else ConstraintStyle.MINIMAL,
        still_image=args.still,
        intra_only=args.intra,
        screen_content=args.scc,
        scalable=args.scalable,
        multiview=args.multiview,
    )

    try:
        results = resolve(content, codecs)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.bare:
        print_bare(results)
    else:
        print_results(content, results, verbose=True)


if __name__ == "__main__":
    main()

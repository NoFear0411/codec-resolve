# codec_resolve

Resolve, decode, and validate video codec strings for HEVC, AV1, and Dolby Vision.

## What it does

Codec strings like `hvc1.2.4.L153.B0` or `av01.0.13M.10.0.110.09.16.09.0` show up in HLS manifests (`EXT-X-STREAM-INF`), DASH MPDs, and browser APIs (`canPlayType()`, `MediaSource.isTypeSupported()`). This tool works with those strings in three directions:

- **Resolve** — given content parameters (resolution, fps, bit depth, transfer function), produce the correct codec string
- **Decode** — given a codec string, parse every field back into human-readable form
- **Validate** — given a hybrid pair like `hvc1.2.4.L153.B0, dvh1.08.06`, cross-check that the HEVC base layer and DV enhancement layer are actually compatible

Useful when building manifest generators, debugging playback issues, or testing browser codec support.

## Setup

```bash
git clone https://github.com/NoFear0411/codec-resolve.git
cd codec-resolve
```

No dependencies. Python 3.8+.

## Usage

Runs standalone or as a module:

```bash
# Standalone
./codec-resolve --decode "hvc1.2.4.L153.B0"
./codec-resolve --codec hvc1 -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020

# Module
python -m codec_resolve --decode "av01.0.13M.10.0.110.09.16.09.0"
python -m codec_resolve --codec av01 -r 4k --fps 60 -d 10 -c 420 -t pq -g bt2020
```

### Decode examples

```bash
# Single codecs
./codec-resolve --decode "hvc1.2.4.L153.B0"
./codec-resolve --decode "av01.0.13M.10.0.110.09.16.09.0"
./codec-resolve --decode "dvh1.08.06"
./codec-resolve --decode "dav1.10.09/db4h"

# Hybrid pairs — runs cross-validation
./codec-resolve --decode "hvc1.2.4.L153.B0, dvh1.08.06"
./codec-resolve --decode "av01.0.13M.10, dav1.10.06/db4h"
```

### Resolve examples

```bash
./codec-resolve --codec hvc1 -r 1080p --fps 60 -d 8 -c 420 -t sdr -g bt709
./codec-resolve --codec hvc1 -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020
./codec-resolve --codec av01 -r 4k --fps 60 -d 12 -c 422 -t pq -g bt2020
./codec-resolve --codec dvh1 -r 4k --fps 24 -d 10 -c 420 -t pq -g bt2020
./codec-resolve --codec all -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020
```

Resolution presets: `720p`, `1080p`, `1440p`, `4k`, `8k` (or `WxH`)

### As a library

```python
from codec_resolve import (
    decode_codec_string, decode_hybrid_string,
    resolve, Content, Chroma, Transfer, Gamut,
)

# Decode
result = decode_codec_string("av01.0.13M.10.0.110.09.16.09.0")
result["profile_name"]   # "Main"
result["level_name"]     # "5.1"
result["bit_depth"]      # 10
result["verdict"]        # "VALID"

# Validate a hybrid pair
hybrid = decode_hybrid_string("hvc1.2.4.L153.B0, dvh1.08.06")
hybrid["validation"]["valid"]  # True

# Resolve content to codec string
content = Content(3840, 2160, 60, 10, Chroma.YUV420, Transfer.PQ, Gamut.BT2020)
results = resolve(content, ["av01"])
results[0].codec_string  # "av01.0.13M.10.0.110.09.16.09.0"
```

## Sample output

### Resolve: 4K HDR10 HEVC
`./codec-resolve --codec hvc1 -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020`
```
  Content: 3840×2160@30fps / 10-bit / 4:2:0 / PQ / BT2020

  hvc1.2.4.L150.B0
    ├─ Family:  HEVC
    ├─ Profile: HEVC Main 10 (profile 2)
    ├─ Level:   Level 5.0 (level_idc=150)
    ├─ Tier:    Main
    ├─ Constraint bytes: minimal (matches x265/FFmpeg)
    └─ hvc1: parameter sets out of band (sample entry)
```

### Decode: HEVC
`./codec-resolve --decode "hvc1.2.4.L153.B0"`
```
  ┌─ hvc1.2.4.L153.B0
  │
  │  Family:   hevc
  │  Entry:    hvc1  (Parameter sets out of band (sample entry))
  │
  │  Profile:  2 — Main 10
  │  Spec:     8-10-bit, 4:2:0
  │  Level:    5.1 (level_idc=153)
  │  Tier:     Main
  │  Max res:  3840×2160 (4K UHD)
  │  Max rate: 40,000 kbps (Main tier)
  │
  │  Backward-compatible with:
  │    • 2 (Main 10)
  │
  │  Stream characteristics:
  │    Scan:        Progressive
  │    Frame only:  Yes — no field coding
  │    Bit depth:   ≤10-bit (no depth constraint — profile maximum)
  │    Chroma:      ≤4:2:0 (profile maximum)
  │    Lower BR:    No — full level bitrate available
  │
  │  Constraint bytes (1): 0xB0
  │    Style:     Minimal (source flags only, x265/FFmpeg style)
  │    Set (=1):   general_progressive_source, general_non_packed_constraint, general_frame_only_constraint
  │    Clear (=0): general_interlaced_source, general_max_12bit_constraint, general_max_10bit_constraint, general_max_8bit_constraint, general_max_422chroma_constraint
  │
  │  ╸ Verdict: ✓ VALID
  └─
```

### Decode: AV1
`./codec-resolve --decode "av01.0.13M.10.0.110.09.16.09.0"`
```
  ┌─ av01.0.13M.10.0.110.09.16.09.0
  │
  │  Family:   av1
  │  Entry:    av01
  │
  │  Profile:  0 — Main
  │  Level:    5.1 / Main tier
  │  Depth:    10-bit
  │  Chroma:   4:2:0 (subsampling 1,1 position 0)
  │  Color:    BT.2020 / BT.2100 primaries, PQ (SMPTE ST 2084) transfer, BT.2020 NCL matrix
  │  Range:    Limited (studio swing)
  │  Bitrate:  ≤40.0 Mbps (Main tier × P0 factor 1.0×)
  │
  │  Validation:
  │    ℹ [AV1_COLOR_SPACE] Color: BT.2020 / BT.2100 / PQ (SMPTE ST 2084) / BT.2020 NCL / Limited (studio swing)
  │    ℹ [AV1_BITRATE_CAP] Effective max bitrate: 40.0 Mbps (Main tier × P0 factor 1.0×)
  │
  │  ╸ Verdict: ✓ VALID
  └─
```

### Decode: Dolby Vision
`./codec-resolve --decode "dvh1.08.06"`
```
  ┌─ dvh1.08.06
  │
  │  Family:   dv
  │  Entry:    dvh1  (HEVC base layer, RPU out-of-band (sample description — HLS/MP4))
  │  BL codec: HEVC
  │
  │  Profile:  8 — Profile 8 (single-layer + RPU)
  │    8.1: HDR10-compatible (PQ + BT.2020/P3, 10-bit)
  │    8.2: SDR-compatible (SDR + BT.709, 10-bit)
  │    8.4: HLG-compatible (HLG + BT.2020, 10-bit)
  │    ℹ Sub-profile (8.1/8.2/8.4) is determined by bl_signal_compatibility_id in the RPU, not visible in the codec string alone
  │  EL:       None (single-layer + RPU)
  │  Cross:    HEVC Main 10 (HDR10/SDR/HLG depending on sub-profile)
  │  Status:   Current ★ (dominant streaming profile)
  │
  │  Level:    06
  │  Max cap:  3840×2160@24fps
  │  Max rate: 50,000 kbps (Main)
  │            100,000 kbps (High)
  │
  │  ╸ Verdict: ✓ VALID
  └─
```

### Decode: HEVC + Dolby Vision hybrid
`./codec-resolve --decode "hvc1.2.4.L153.B0, dvh1.08.06"`
```
  ╔══ HLS Hybrid Codec: hvc1.2.4.L153.B0, dvh1.08.06
  ║  Status: ✓ VALID
  ║
  ║  ┌─ HEVC Base Layer: hvc1.2.4.L153.B0
  ║  │  Profile:  2 (Main 10)
  ║  │  Level:    5.1 / Main tier
  ║  │  Max res:  3840×2160 (4K UHD)
  ║  │  Max rate: 40,000 kbps
  ║  │  Stream:   ≤10-bit (no depth constraint — profile maximum), ≤4:2:0 (profile maximum)
  ║  └─
  ║
  ║  ┌─ Dolby Vision Supplement: dvh1.08.06
  ║  │  Profile:  8 — Profile 8 (single-layer + RPU)
  ║  │    8.1: HDR10-compatible (PQ + BT.2020/P3, 10-bit)
  ║  │    8.2: SDR-compatible (SDR + BT.709, 10-bit)
  ║  │    8.4: HLG-compatible (HLG + BT.2020, 10-bit)
  ║  │    ℹ Sub-profile (8.1/8.2/8.4) is determined by bl_signal_compatibility_id in the RPU, not visible in the codec string alone
  ║  │  EL:       None (single-layer + RPU)
  ║  │  Level:    06 — 3840×2160@24fps
  ║  └─
  ║
  ║  Cross-validation:
  ║    ✓ HEVC profile 2 (Main 10) matches DV 8.1 requirement (HEVC Main 10)
  ║    ⚠ HEVC L5.1 throughput (534,773,760 samples/s) exceeds DV L06 (199,065,600 samples/s) by 2.7×. DV RPU frame size is sufficient, but HEVC may deliver frames faster than the DV level's rated throughput
  ║    Single-layer + RPU: non-DV players decode BL as HDR10 (PQ + BT.2020)
  ║    ℹ DV L06 allows up to 100,000 kbps but HEVC Main tier caps at 40,000 kbps — HEVC tier is the bottleneck
  ║    ℹ RPU overhead: DV metadata adds ~50-250 kbps. Safe video bitrate ceiling for HEVC L5.1 Main tier: ≤39,500 kbps (level max 40,000 minus ~500 RPU margin)
  ║    Metadata delivery: out-of-band (sample description — HLS/MP4)
  ║    ⚠ Entry mismatch: hvc1 (out-of-band) + dvh1 (in-band). HEVC and DV parameter delivery methods should match. Expected: hvc1+dvhe. Hardware decoders (LG C4, Apple TV) may fail to initialize the HDR pipeline
  ║    bl_signal_compatibility_id=1: BL is valid HDR10. Strip RPU → standard PQ/BT.2020 10-bit playback
  ║
  ║  Fallback behavior:
  ║    DV-capable:     Full Dolby Vision rendering
  ║    Non-DV player:  HDR10 (PQ + BT.2020)
  ║    Fallback mode:  Signaled (bl_signal_compatibility_id in RPU)
  ║
  ║  Layer structure:   BL+RPU
  ║  Metadata delivery: dvh1=out-of-band (HLS/MP4) / dvhe=in-band (DASH/TS)
  ║
  ║  ╸ Verdict: ✓ VALID
  ╚══
```

## Codec coverage

| Family | Entries | Profiles | Levels |
|--------|---------|----------|--------|
| HEVC | `hvc1`, `hev1` | 13 (Main through MVRExt, SCC, HT, Scalable, Multiview) | 1.0–6.2 |
| AV1 | `av01` | Main, High, Professional | 2.0–6.3 |
| Dolby Vision | `dvhe`, `dvh1`, `dvav`, `dva1`, `dav1` | P5, P7, P8 (8.1/8.2/8.4), P9, P10, P20 | 13 levels |

### Hybrid validation checks

| Pair | What gets checked |
|------|-------------------|
| HEVC + DV | Profile contract, level headroom, level paradox, HLS brand ↔ compat_id, entry sync, INBLD flag, tier bitrate, fallback behavior |
| AV1 + DV | Base codec match, profile contract, DV→AV1 level mapping, color consistency, brand validation, entry sync, tier bitrate |

### HLS brands (SUPPLEMENTAL-CODECS)

| Brand | Meaning |
|-------|---------|
| `db1p` | DV + HDR10 (PQ) |
| `db2g` | DV + SDR (BT.709) |
| `db4h` | DV + HLG |
| `cdm4` | HDR10+ (ST 2094-40) |

## Contributing

Currently covers HEVC, AV1, and Dolby Vision. Planned additions:

**Video:** AVC/H.264 (`avc1.PPCCLL`), VP9 (`vp09.PP.LL.DD`)
**Audio:** AAC (`mp4a.40.XX`), AC-3, E-AC-3 (`ec-3`), Opus, FLAC, DTS

Each codec family lives in its own subdirectory (`hevc/`, `av1/`, `dv/`). They never import each other — `hybrid.py` is the only bridge. Adding a new codec means:

1. Create a directory (e.g. `avc/`) with `profiles.py`, `levels.py`, `decode.py`
2. Add entry points to `registry.py`
3. Add resolve logic to `resolve.py`
4. Add decode routing to `hybrid.py`
5. Add tests to `tests.py`

```bash
python -m codec_resolve --test
python -m codec_resolve --decode-test
```

## Project structure

```
codec-resolve/
├── codec-resolve              Standalone launcher
├── codec_resolve/
│   ├── models.py              Content dataclass, H.273 color tables
│   ├── registry.py            FourCC → codec family registry
│   ├── resolve.py             Forward resolver
│   ├── hybrid.py              Cross-validation engine
│   ├── display.py             Terminal formatters
│   ├── hls.py                 HLS brand registry
│   ├── tests.py               118 tests
│   ├── hevc/                  HEVC profiles, levels, decoder
│   ├── av1/                   AV1 profiles, levels, decoder
│   └── dv/                    DV profiles, levels, decoder
├── CHANGELOG.md
└── LICENSE
```

## Spec references

| Spec | Coverage |
|------|----------|
| ITU-T H.265 | HEVC profiles, levels, constraint flags |
| ISO/IEC 14496-15 Annex E | HEVC codec string format |
| AV1 Bitstream Spec Annex A | AV1 levels, tiers |
| AV1-ISOBMFF v1.3.0 §5 | AV1 codec string format |
| ETSI TS 103 572 | DV profiles, levels, compatibility |
| ITU-T H.273 | Color primaries, transfer characteristics, matrix coefficients |
| Apple HLS Authoring Spec §3.1 | SUPPLEMENTAL-CODECS brands |

## License

LGPL-3.0-or-later — see [LICENSE](LICENSE).

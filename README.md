# codec_resolve

**Bidirectional video codec string resolver, decoder & validator for HEVC, AV1, and Dolby Vision.**

Parse `hvc1.2.4.L153.B0` or `av01.0.13M.10.0.110.09.16.09.0` into every field. Generate spec-correct codec strings from content parameters. Cross-validate hybrid `HEVC+DV` and `AV1+DV` pairs with 30+ semantic checks. Zero dependencies, pure Python, 118 tests.

---

## What does this solve?

Video codec strings like `hvc1.2.4.L153.B0` and `av01.0.13M.10` are compact, opaque, and easy to get wrong. They encode profiles, levels, tiers, bit depth, chroma, color primaries, transfer functions, and compatibility constraints — all packed into a dot-separated string that's critical for HLS manifests, DASH MPDs, browser `canPlayType()`, and media server transcoding decisions.

Getting a single field wrong means silent playback failures, unnecessary transcodes, or broken HDR metadata. There's no existing tool that both **generates** and **validates** these strings against the actual spec tables, let alone cross-validates hybrid Dolby Vision pairings.

**codec_resolve** closes that gap:

- **Forward resolve:** Describe your content (resolution, fps, depth, HDR format) → get the correct codec string
- **Reverse decode:** Paste any codec string → get every parsed field with human-readable names
- **Cross-validate:** Feed an HLS hybrid pair like `"hvc1.2.4.L153.B0, dvh1.08.06"` → get a full compatibility audit

## Quick start

```bash
# Clone and run — no install needed, no dependencies
git clone https://github.com/YOUR_USERNAME/codec_resolve.git
cd codec_resolve

# Run tests (118 pass)
python run.py --test
python run.py --decode-test

# Decode a codec string
python run.py --decode "av01.0.13M.10.0.110.09.16.09.0"
python run.py --decode "hvc1.2.4.L153.B0"
python run.py --decode "hvc1.2.4.L153.B0, dvh1.08.06"

# Generate a codec string from content parameters
python run.py --codec av01 -r 4k --fps 60 -d 10 -c 420 -t pq -g bt2020
python run.py --codec hvc1 -r 1080p --fps 30 -d 8 -c 420 -t sdr -g bt709
```

Or use the module form:
```bash
python -m codec_resolve --decode "av01.0.13M.10"
```

## Use as a library

```python
from codec_resolve import (
    decode_codec_string, decode_hybrid_string, decode_av1, decode_hevc,
    resolve, Content, Chroma, Transfer, Gamut,
)

# Decode any codec string
result = decode_codec_string("av01.0.13M.10.0.110.09.16.09.0")
print(result["profile_name"])    # "Main"
print(result["level_name"])      # "5.1"
print(result["bit_depth"])       # 10
print(result["color_primaries_name"])  # "BT.2020 / BT.2100"
print(result["verdict"])         # "VALID"

# Cross-validate a hybrid pair
hybrid = decode_hybrid_string("hvc1.2.4.L153.B0, dvh1.08.06")
print(hybrid["validation"]["valid"])  # True

# Forward resolve: describe content → get codec string
content = Content(
    width=3840, height=2160, fps=60,
    bit_depth=10, chroma=Chroma.YUV420,
    transfer=Transfer.PQ, gamut=Gamut.BT2020
)
results = resolve(content, ["av01"])
print(results[0].codec_string)  # "av01.0.13M.10.0.110.09.16.09.0"
```

## Example output

### AV1 decode
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
  │  ╸ Verdict: ✓ VALID
  │
  └─
```

### HEVC + Dolby Vision hybrid cross-validation
```
  ╔══ HLS Hybrid Codec: hvc1.2.4.L153.B0, dvh1.08.06
  ║  Status: ✓ VALID
  ║
  ║  ┌─ HEVC Base Layer: hvc1.2.4.L153.B0
  ║  │  Profile:  2 (Main 10)
  ║  │  Level:    5.1 / Main tier
  ║  └─
  ║
  ║  ┌─ Dolby Vision Supplement: dvh1.08.06
  ║  │  Profile:  8 — DV Profile 8.1 (HDR10-Compat)
  ║  │  Level:    06 — 3840×2160@24fps
  ║  └─
  ║
  ║  Cross-validation:
  ║    ✓ Base layer: HEVC Main 10 (Profile 2) — correct for DV Profile 8
  ║    ✓ Level headroom: HEVC L5.1 ≥ DV L06 minimum (HEVC L5.0)
  ║    ✓ Entry sync: hvc1+dvh1 — out-of-band metadata
  ║
  ║  ╸ Verdict: ✓ VALID
  ╚══
```

## Supported codecs

| Family | Entries | Profiles | Levels |
|--------|---------|----------|--------|
| **HEVC** | `hvc1`, `hev1` | 13 (Main through MVRExt, incl. SCC, HT, Scalable, Multiview) | 19 levels (1.0–6.2) |
| **AV1** | `av01` | 3 (Main, High, Professional) | 14 levels (2.0–6.3) + unconstrained |
| **Dolby Vision** | `dvhe`, `dvh1`, `dvav`, `dva1`, `dav1` | P5, P7, P8 (sub: 8.1/8.2/8.4), P9, P10, P20 | 13 levels |

### Hybrid cross-validation

| Pair | Checks |
|------|--------|
| **HEVC + DV** | Base codec match, profile contract, level headroom, level paradox detection, HLS brand ↔ compat_id, entry sync, tier bitrate, fallback behavior |
| **AV1 + DV** | Base codec match (P10→AV1), profile contract (P0 Main 10-bit), level headroom via DV→AV1 mapping, color consistency, brand validation, entry sync (dav1), tier bitrate |

### HLS brands (SUPPLEMENTAL-CODECS)

| Brand | Meaning |
|-------|---------|
| `/db1p` | DV cross-compatible with HDR10 (PQ) |
| `/db2g` | DV cross-compatible with HLG (VUI=18) |
| `/db4h` | DV cross-compatible with HLG (VUI=14) |
| `/cdm4` | HDR10+ (SMPTE ST 2094-40) |

## CLI reference

### Decode (reverse)
```bash
# Single codec
python run.py --decode "hvc1.2.4.L153.B0"
python run.py --decode "av01.0.13M.10"
python run.py --decode "dvh1.08.06"
python run.py --decode "dav1.10.09/db4h"

# Hybrid pair
python run.py --decode "hvc1.2.4.L153.B0, dvh1.08.06"
python run.py --decode "av01.0.13M.10, dav1.10.06/db4h"
```

### Resolve (forward)
```bash
python run.py --codec ENTRY -r RES --fps FPS -d DEPTH -c CHROMA -t TRANSFER -g GAMUT [options]

# HEVC
python run.py --codec hvc1 -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020
python run.py --codec hvc1 -r 1080p --fps 60 -d 8 -c 420 -t sdr -g bt709
python run.py --codec hvc1 -r 4k --fps 60 -d 10 -c 422 -t pq -g bt2020  # → RExt

# AV1
python run.py --codec av01 -r 4k --fps 60 -d 10 -c 420 -t pq -g bt2020
python run.py --codec av01 -r 4k --fps 60 -d 12 -c 422 -t pq -g bt2020  # → Professional

# Dolby Vision
python run.py --codec dvh1 -r 4k --fps 24 -d 10 -c 420 -t pq -g bt2020

# All codecs at once
python run.py --codec all -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020
```

Resolution presets: `720p`, `1080p`, `1440p`, `4k`, `8k`

### Tests
```bash
python run.py --test           # 47 forward-resolve tests
python run.py --decode-test    # 71 decode + hybrid + brand + roundtrip tests
```

## Spec sources

- **HEVC:** ITU-T H.265 (profiles, levels, constraint flags), ISO/IEC 14496-15 Annex E (codec string format)
- **AV1:** AV1 Bitstream Spec Annex A (levels, tiers), AV1-ISOBMFF v1.3.0 §5 (codec string format)
- **Dolby Vision:** ETSI TS 103 572 (profiles, levels, compatibility), DASH-IF IOP §8.2.1 (DV signaling)
- **Color:** ITU-T H.273 (color primaries, transfer characteristics, matrix coefficients)
- **HLS:** Apple HLS Authoring Spec §3.1 (SUPPLEMENTAL-CODECS brands)

## Project structure

```
codec_resolve/                 6,993 lines
├── models.py                  Shared enums, Content, ResolvedCodec, H.273 color tables
├── resolve.py                 Forward resolver (Content → codec strings)
├── hybrid.py                  Cross-validation engine + codec routing
├── display.py                 Pretty-printers
├── hls.py                     HLS brand registry
├── tests.py                   118 tests
├── hevc/                      HEVC module (13 profiles, 19 levels, full decoder)
├── av1/                       AV1 module (3 profiles, 14 levels, full decoder)
└── dv/                        Dolby Vision module (10 compat entries, 13 levels)
```

Architecture: `hevc/`, `av1/`, and `dv/` are siblings that never import each other. `hybrid.py` is the only bridge.

## Requirements

Python 3.8+. No external dependencies.

## License

MIT

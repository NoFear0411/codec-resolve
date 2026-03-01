# CODEMAP.md — codec_resolve Package Reference
## 7,857 lines · 140 tests · zero dependencies
### Bidirectional: resolve ↔ decode ↔ validate ↔ hybrid
### Codec families: HEVC · AV1 · VP9 · Dolby Vision (Profiles 5/7/8/9/10/20)

---

## Package Structure

```
codec_resolve/                    7,857 lines total
├── __init__.py          41       Public API re-exports
├── __main__.py         501       CLI: argparse, dispatch, help
├── models.py           284       Shared enums + dataclasses + H.273 color tables
├── registry.py          32       Codec entry point registry (FourCC → family)
├── hls.py              127       HLS brand registry + strip_hls_brands()
├── resolve.py          279       Master resolver (HEVC + AV1 + VP9 + DV)
├── hybrid.py           820       Cross-validation + routing (structured notes)
├── display.py          668       Pretty-printers (standalone + hybrid)
├── tests.py          1,049       140 tests
├── hevc/
│   ├── __init__.py       1
│   ├── profiles.py     353       13 HEVC profiles + constraint byte engine
│   ├── levels.py       113       HEVC level table (1.0–6.2)
│   └── decode.py     1,592       Full HEVC decoder + 14 semantic checks
├── av1/
│   ├── __init__.py       0
│   ├── profiles.py     127       3 AV1 profiles + resolver + string formatter
│   ├── levels.py        98       14 AV1 levels (2.0–6.3) + tier rules
│   └── decode.py       408       AV1 codec string parser + 9 validation checks
├── vp9/
│   ├── __init__.py       0
│   ├── profiles.py     133       4 VP9 profiles + resolver + string formatter
│   ├── levels.py        92       13 VP9 levels (1–6.2) + resolver
│   └── decode.py       315       VP9 codec string parser + 7 validation checks
└── dv/
    ├── __init__.py       1
    ├── profiles.py     345       10 DV compat entries + METADATA_DELIVERY
    ├── levels.py       145       DV level table + HEVC mapping + AV1 mapping
    └── decode.py       335       DV decoder (triplet/unified/brand)
```

**Architecture rule:** `hevc/`, `dv/`, `av1/`, and `vp9/` are SIBLINGS — they never import each other.
`hybrid.py` is the ONLY bridge between codec families.

---

## Module Reference

### __init__.py (41 lines)
Public API re-exports.
```python
from codec_resolve import (
    resolve, decode_codec_string, decode_hybrid_string,
    decode_hevc, decode_av1, decode_vp9, decode_dv,
    validate_hybrid, validate_av1_hybrid,
    Content, Chroma, Transfer, Gamut, Scan, Tier,
    ConstraintStyle, ResolvedCodec,
)
```

### __main__.py (501 lines)
CLI entry point. `./codec-resolve [options]` or `python -m codec_resolve [options]`

| Line | Symbol | Description |
|------|--------|-------------|
| 15 | `RESOLUTION_PRESETS` | Named presets: 720p, 1080p, 4k, 8k, etc. |
| 24 | `parse_resolution(s)` | WxH or preset name → (w, h) |
| 37 | `parse_codecs(s)` | Codec aliases → entry list. Supports: hvc1/hev1/av01/dvhe/dvh1/dva1/dvav/dav1, aliases: hevc/av1/dv/all |
| 97 | `HELP_TEXT` | Extended help with examples for all codec families |
| 310 | `main()` | Argparse dispatch: --test, --decode-test, --decode, --codec |

Key CLI examples:
```bash
python -m codec_resolve --test                                  # 55 resolve tests
python -m codec_resolve --decode-test                           # 85 decode/hybrid/brand/roundtrip tests
python -m codec_resolve --decode "av01.0.13M.10"                # AV1 standalone
python -m codec_resolve --decode "vp09.02.50.10.01.09.16.09.00" # VP9 standalone
python -m codec_resolve --decode "av01.0.13M.10, dav1.10.06"    # AV1+DV hybrid
python -m codec_resolve --codec vp09 -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020
python -m codec_resolve --codec hvc1 -r 4k --fps 30 -d 10 -c 420 -t pq -g bt2020
python -m codec_resolve --decode "hvc1.2.4.L153.B0, dvh1.08.06" # HEVC+DV hybrid
```

### models.py (284 lines)
Shared data models and ITU-T H.273 color parameter tables.

| Line | Symbol | Description |
|------|--------|-------------|
| 11 | `Chroma` | Enum: MONO, YUV420, YUV422, YUV444 |
| 32 | `Transfer` | Enum: SDR, PQ, HLG |
| 48 | `Gamut` | Enum: BT709, BT2020, P3 |
| 66 | `Scan` | Enum: PROGRESSIVE, INTERLACED |
| 71 | `Tier` | Enum: MAIN, HIGH |
| 76 | `ConstraintStyle` | Enum: MINIMAL, FULL |
| 105 | `Content` | Dataclass: full media descriptor (resolution, fps, depth, chroma, transfer, gamut, DV/HEVC overrides) |
| 159 | `.luma_ps` | Computed: width × height |
| 163 | `.luma_sps` | Computed: luma_ps × fps |
| 166 | `.describe()` | Human-readable summary |
| 192 | `ResolvedCodec` | Dataclass: codec_string, entry, family, profile_name, level_name, tier_name, notes |
| 209 | `COLOR_PRIMARIES` | ITU-T H.273 Table 2 (22 entries: 0=Identity, 1=BT.709, 9=BT.2020, 12=P3-D65, etc.) |
| 225 | `TRANSFER_CHARACTERISTICS` | ITU-T H.273 Table 3 (18 entries: 1=BT.709, 16=PQ, 18=HLG, etc.) |
| 246 | `MATRIX_COEFFICIENTS` | ITU-T H.273 Table 4 (14 entries: 0=Identity, 1=BT.709, 9=BT.2020 NCL, etc.) |
| 266 | `TRANSFER_TO_TC` | Transfer enum → expected tc value mapping |
| 272 | `GAMUT_TO_CP` | Gamut enum → expected cp value mapping |
| 278 | `CP_TO_MC` | Color primaries → default matrix coefficients mapping |

### registry.py (32 lines)
Codec entry point registry — single source of truth for FourCC → family dispatch.

| Line | Symbol | Description |
|------|--------|-------------|
| 3 | `CODEC_ENTRIES` | Dict: 9 FourCC entries → {family, base_codec, is_dv} |
| 15 | `ENTRY_ALIASES` | Dict: 7 alias groups (hevc, av1, vp9, dv, dv-avc, dv-av1, all) |
| 25 | `ALL_ENTRIES` | Set of all valid entry points |

**CODEC_ENTRIES:**
| Entry | Family | Base Codec | DV? |
|-------|--------|------------|-----|
| hvc1, hev1 | hevc | HEVC | No |
| av01 | av1 | AV1 | No |
| vp09 | vp9 | VP9 | No |
| dvhe, dvh1 | dv | HEVC | Yes |
| dvav, dva1 | dv | AVC | Yes |
| dav1 | dv | AV1 | Yes |
| dvc1, dvhp | dv | HEVC | Yes (non-standard) |

### hls.py (127 lines)
HLS SUPPLEMENTAL-CODECS brand registry + shared brand stripping.

| Line | Symbol | Description |
|------|--------|-------------|
| 10 | `strip_hls_brands(s)` | Strip `/brand` suffix → (clean_string, brands_list, unknown_brands) |
| 49 | `HlsDvBrand` | NamedTuple: description, dv_profiles, spec_owner, inferred_compat_id, video_range |
| 55 | `HLS_DV_BRANDS` | Dict: 4 brands (db1p, db2g, db4h, cdm4) |

| Brand | Meaning | compat_id | video_range |
|-------|---------|-----------|-------------|
| `db1p` | DV cross-compatible with HDR10 (PQ) | 1 | PQ |
| `db2g` | DV cross-compatible with SDR (BT.709) | 2 | SDR |
| `db4h` | DV cross-compatible with HLG (BT.2100) | 4 | HLG |
| `cdm4` | HDR10+ (SMPTE 2094-40) | — | PQ |

### resolve.py (279 lines)
Master forward resolver: Content → codec string(s). Uses `METADATA_DELIVERY` from dv/profiles.py.

| Line | Symbol | Description |
|------|--------|-------------|
| 10 | `resolve(content, codecs)` | Main entry: dispatches to _resolve_hevc, _resolve_dv, _resolve_av1, _resolve_vp9 |
| 33 | route `av01` | → `_resolve_av1(content, "av01")` |
| 40 | route `vp09` | → `_resolve_vp9(content, "vp09")` |
| 48 | `_resolve_hevc(c, entry)` | HEVC forward resolve |
| 102 | `_resolve_dv(c, entry)` | DV forward resolve (uses METADATA_DELIVERY) |
| 165 | `_resolve_av1(c, entry)` | AV1 forward resolve: profile → level → tier → color → format_av1_string() |
| 224 | `_resolve_vp9(c, entry)` | VP9 forward resolve: profile → level → CC → color → format_vp9_string() |

### hybrid.py (820 lines)
Cross-validation engine + codec string routing. Uses `CODEC_ENTRIES` from registry.py.
Notes are structured dicts: `{"severity": "pass"|"warning"|"info"|"note", "message": ...}`.

| Line | Symbol | Description |
|------|--------|-------------|
| 21 | `validate_hybrid(hevc, dv)` | HEVC+DV cross-validation (22+ checks, structured notes) |
| 512 | `validate_av1_hybrid(av1, dv)` | AV1+DV cross-validation (7 checks, structured notes) |
| 718 | `decode_codec_string(s)` | Auto-detect family via CODEC_ENTRIES → decode |
| 740 | `decode_hybrid_string(s)` | Parse "base, dv" pair → decode both → cross-validate |

**AV1+DV hybrid checks (validate_av1_hybrid):**
| Check | Description |
|-------|-------------|
| A1 | Base codec match — DV P10 requires AV1 base (entry `dav1`) |
| A2 | AV1 profile contract — DV P10 needs AV1 P0 (Main), 10-bit, non-mono |
| A3 | Level headroom — DV level → min AV1 seq_level_idx via DV_TO_AV1_LEVEL_IDX |
| A4 | Color consistency — Brand vs transfer_characteristics (PQ=16, HLG=18) |
| A5 | Brand validation — db4h/db1p/db2g valid for P10; cdm4 for standalone AV1 |
| A6 | Entry sync — dav1 only valid DV entry for AV1 base |
| A7 | Tier bitrate — AV1 tier cap × BitrateProfileFactor vs DV level allowance |

**HEVC+DV hybrid checks (validate_hybrid):**
| Check | Description |
|-------|-------------|
| H1 | Base codec match — DV profile → required HEVC profile(s) |
| H2 | Profile contract — DV P8→Main 10, P5→Main 10, P7→Main 10, P9→AVC |
| H3 | Level headroom — DV level → min HEVC level_idc |
| H4 | Level paradox — HEVC frame capacity vs DV RPU metadata buffer |
| H5 | HLS brand ↔ compat_id — db4h→4, db1p→1, db2g→2 |
| H6 | Entry sync — dvh1/dvhe=HEVC, dav1=AV1, dvav/dva1=AVC |
| H7+ | Tier bitrate, fallback, metadata delivery, layer structure |

### display.py (668 lines)
Pretty-printers for all output types. Owns emoji prefix mapping for structured notes via `_NOTE_PREFIX`.

| Line | Symbol | Description |
|------|--------|-------------|
| 8 | `print_results(content, results)` | Forward-resolve output with optional DV cross-validation |
| 86 | `print_bare(results)` | Minimal output (--bare flag) |
| 102 | `print_hybrid(result)` | Hybrid display — handles BOTH HEVC+DV and AV1+DV |
| 250 | `print_decoded(d)` | Standalone decode display — HEVC, AV1, or DV family |

Note rendering: `_NOTE_PREFIX = {"pass": "✓ ", "warning": "⚠ ", "info": "ℹ ", "note": ""}`

AV1 standalone display format:
```
  ┌─ av01.0.13M.10.0.110.09.16.09.0
  │  Profile:  0 — Main
  │  Level:    5.1 / Main tier
  │  Depth:    10-bit
  │  Chroma:   4:2:0 (subsampling 1,1 position 0)
  │  Color:    BT.2020 primaries, PQ transfer, BT.2020 NCL matrix
  │  Range:    Limited (studio swing)
  │  Bitrate:  ≤40.0 Mbps (Main tier × P0 factor 1.0×)
  └─
```

AV1+DV hybrid display format:
```
  ╔══ HLS Hybrid Codec: av01.0.13M.10, dav1.10.06
  ║  ┌─ AV1 Base Layer: av01.0.13M.10
  ║  │  Profile/Level/Depth/Color
  ║  └─
  ║  ┌─ Dolby Vision Supplement: dav1.10.06
  ║  │  Profile/Level/EL
  ║  └─
  ║  Cross-validation: ✓ checks
  ╚══
```

---

## av1/ Module (633 lines)

### av1/profiles.py (127 lines)
AV1 profile definitions and selection logic.
Source: AV1 Bitstream Spec §6.4.1, AV1-ISOBMFF §5.

| Line | Symbol | Description |
|------|--------|-------------|
| 15 | `AV1ProfileDef` | Dataclass: seq_profile, name, max_bit_depth, allowed_chroma, mono_allowed |
| 28 | `AV1_PROFILE_DEFS` | 3 profiles (see table below) |
| 52 | `AV1_PROFILE_NAMES` | {0: "Main", 1: "High", 2: "Professional"} |
| 59 | `VALID_BIT_DEPTHS` | Per-profile valid depths: P0→{8,10}, P1→{8,10}, P2→{8,10,12} |
| 71 | `CHROMA_FROM_SUBSAMPLING` | (sx,sy) → Chroma enum |
| 77 | `SUBSAMPLING_FROM_CHROMA` | Chroma enum → (sx,sy) |
| 84 | `CHROMA_SAMPLE_POSITION_NAMES` | {0: "Unknown", 1: "Vertical", 2: "Colocated"} |
| 94 | `resolve_av1_profile(c)` | Content → profile index (0/1/2) |
| 108 | `BITRATE_PROFILE_FACTOR` | {0: 1.0, 1: 2.0, 2: 3.0} |
| 113 | `format_av1_string(...)` | → "av01.P.LLT.DD.M.CCC.cp.tc.mc.F" |

**AV1 Profile Table:**
| Profile | Name | Max Depth | Chroma | Mono | Notes |
|---------|------|-----------|--------|------|-------|
| 0 | Main | 10-bit | 4:2:0 only | Yes | Standard consumer (streaming, browsers) |
| 1 | High | 10-bit | 4:2:0 + 4:4:4 | No | High-fidelity 4:4:4 content |
| 2 | Professional | 12-bit | 4:2:0 + 4:2:2 + 4:4:4 | Yes | Broadcast mastering, 12-bit |

**BitrateProfileFactor:** P0 → ×1.0, P1 → ×2.0, P2 → ×3.0

### av1/levels.py (98 lines)
AV1 level table and tier resolution.
Source: AV1 Bitstream Spec Annex A.

| Line | Symbol | Description |
|------|--------|-------------|
| 13 | `AV1Level` | Dataclass: seq_level_idx, name, max_pic_size, max_h/v_size, max_display_rate, main_mbps, high_mbps, max_tiles, max_tile_cols |
| 33 | `AV1_LEVELS` | 14 defined levels (list) |
| 51 | `AV1_LEVEL_LOOKUP` | {seq_level_idx: AV1Level} dict |
| 54 | `_level_name_from_idx(idx)` | Formula: X = 2 + (idx >> 2), Y = idx & 3 |
| 63 | `resolve_av1_level(c)` | Content → minimum sufficient AV1Level |
| 83 | `resolve_av1_tier(c, level)` | Content + level → tier (0=Main, 1=High) |

**AV1 Level Table:**
| idx | Level | MaxPicSize | Main Mbps | High Mbps | Example |
|-----|-------|-----------|-----------|-----------|---------|
| 0 | 2.0 | 147,456 | 1.5 | — | 426×240@30 |
| 1 | 2.1 | 278,784 | 3.0 | — | 640×360@30 |
| 4 | 3.0 | 665,856 | 6.0 | — | 854×480@30 |
| 5 | 3.1 | 1,065,024 | 10.0 | — | 1280×720@30 |
| 8 | 4.0 | 2,359,296 | 12.0 | 30.0 | 1920×1080@30 |
| 9 | 4.1 | 2,359,296 | 20.0 | 50.0 | 1920×1080@60 |
| 12 | 5.0 | 8,912,896 | 30.0 | 100.0 | 3840×2160@30 |
| 13 | 5.1 | 8,912,896 | 40.0 | 160.0 | 3840×2160@60 |
| 14 | 5.2 | 8,912,896 | 60.0 | 240.0 | 3840×2160@120 |
| 15 | 5.3 | 8,912,896 | 60.0 | 240.0 | 3840×2160@120 |
| 16 | 6.0 | 35,651,584 | 60.0 | 240.0 | 7680×4320@30 |
| 17 | 6.1 | 35,651,584 | 100.0 | 480.0 | 7680×4320@60 |
| 18 | 6.2 | 35,651,584 | 160.0 | 800.0 | 7680×4320@120 |
| 19 | 6.3 | 35,651,584 | 160.0 | 800.0 | 7680×4320@120 |

High tier only available for levels ≥ 4.0 (idx ≥ 8). idx 31 = unconstrained.

### av1/decode.py (408 lines)
AV1 codec string parser with semantic validation. Uses `strip_hls_brands()` from hls.py.
Source: AV1-ISOBMFF §5 (Codecs Parameter String).

| Line | Symbol | Description |
|------|--------|-------------|
| 25 | `_OPTIONAL_DEFAULTS` | Default values when optional fields omitted |
| 35 | `decode_av1(codec_string)` | Main entry: parse + validate → result dict |
| 332 | `_validate_av1(result, findings, level_obj)` | Validation checks |

**AV1 codec string format:**
```
av01.<P>.<LL><T>.<DD>[.<M>.<CCC>.<cp>.<tc>.<mc>.<F>]

Mandatory:  P=profile, LL=level_idx, T=tier(M/H), DD=bitDepth
Optional:   M=mono, CCC=chroma, cp=primaries, tc=transfer, mc=matrix, F=range
Defaults:   M=0, CCC=110, cp=01, tc=01, mc=01, F=0
```

**AV1 Validation Checks:**
| Severity | Code | Trigger |
|----------|------|---------|
| ✗ error | AV1_PROFILE_UNKNOWN | seq_profile not in {0, 1, 2} |
| ✗ error | AV1_LEVEL_UNKNOWN | undefined level (and ≠ 31) |
| ✗ error | AV1_TIER_INVALID | High tier on level < 4.0 |
| ✗ error | AV1_DEPTH_INVALID | Bit depth not valid for profile |
| ✗ error | AV1_CHROMA_INVALID | Chroma not valid for profile |
| ✗ error | AV1_MONO_PROFILE | mono=1 but P1 forbids mono |
| ⚠ warn | AV1_LEVEL_31 | Unconstrained level |
| ℹ info | AV1_OPTIONAL_DEFAULTS | Using default color values |
| ℹ info | AV1_COLOR_SPACE | Resolved color space summary |
| ℹ info | AV1_BITRATE_CAP | Effective max bitrate |

---

## vp9/ Module (540 lines)

### vp9/profiles.py (133 lines)
VP9 profile definitions and selection logic.
Source: VP9 Bitstream Specification §7.2, VP Codec ISO Media File Format Binding §5.

| Line | Symbol | Description |
|------|--------|-------------|
| 14 | `VP9ProfileDef` | Dataclass: profile, name, bit_depths, allowed_chroma, note |
| 26 | `VP9_PROFILE_DEFS` | 4 profiles (see table below) |
| 55 | `VP9_PROFILE_NAMES` | {0: "Profile 0", 1: "Profile 1", 2: "Profile 2", 3: "Profile 3"} |
| 62 | `CHROMA_FROM_CC` | CC value → Chroma enum (0/1→YUV420, 2→YUV422, 3→YUV444) |
| 69 | `CC_FROM_CHROMA` | Chroma enum → CC value (for forward resolve) |
| 76 | `CHROMA_SAMPLE_POSITION_NAMES` | {0: "Vertical (left)", 1: "Colocated (top-left)"} |
| 80 | `VALID_CC_FOR_PROFILE` | Per-profile valid CC values |
| 89 | `resolve_vp9_profile(c)` | Content → profile index (0–3) via orthogonal axes |
| 100 | `format_vp9_string(...)` | → "vp09.PP.LL.DD[.CC.cp.tc.mc.FF]" |

**VP9 Profile Table:**
| Profile | Name | Bit Depths | Chroma | Notes |
|---------|------|------------|--------|-------|
| 0 | Profile 0 | {8} | 4:2:0 only | Standard consumer (streaming, browsers) |
| 1 | Profile 1 | {8} | 4:2:2, 4:4:4 | 8-bit non-4:2:0 content |
| 2 | Profile 2 | {10, 12} | 4:2:0 only | HDR consumer (10/12-bit) |
| 3 | Profile 3 | {10, 12} | 4:2:2, 4:4:4 | Professional (10/12-bit non-4:2:0) |

**Profile selection formula:** `profile = (depth > 8 ? 2 : 0) + (chroma ∉ {4:2:0, mono} ? 1 : 0)`

### vp9/levels.py (92 lines)
VP9 level table and resolution.
Source: VP9 Bitstream Specification Annex A.

| Line | Symbol | Description |
|------|--------|-------------|
| 12 | `VP9Level` | Dataclass: value, name, max_pic_size, max_dim, max_sample_rate, max_bitrate_kbps, max_cpb_kbps, min_cr, max_tiles |
| 30 | `VP9_LEVELS` | 13 defined levels (list) |
| 60 | `VP9_LEVEL_LOOKUP` | {value: VP9Level} dict |
| 63 | `VP9_VALID_LEVEL_VALUES` | Set of all valid level values |
| 67 | `resolve_vp9_level(c)` | Content → minimum sufficient VP9Level |

**VP9 Level Table:**
| Value | Level | MaxPicSize | MaxDim | Max Mbps | Example |
|-------|-------|-----------|--------|----------|---------|
| 10 | 1 | 36,864 | 512 | 0.2 | 256×144@30 |
| 20 | 2 | 73,728 | 960 | 0.8 | 352×240@30 |
| 21 | 2.1 | 245,760 | 1,344 | 1.8 | 480×360@30 |
| 30 | 3 | 552,960 | 2,048 | 3.6 | 720×480@30 |
| 31 | 3.1 | 983,040 | 2,752 | 7.2 | 1280×720@30 |
| 40 | 4 | 2,228,224 | 4,160 | 18.0 | 1920×1080@30 |
| 41 | 4.1 | 2,228,224 | 4,160 | 30.0 | 1920×1080@60 |
| 50 | 5 | 8,912,896 | 8,384 | 60.0 | 3840×2160@30 |
| 51 | 5.1 | 8,912,896 | 8,384 | 120.0 | 3840×2160@60 |
| 52 | 5.2 | 8,912,896 | 8,384 | 180.0 | 3840×2160@120 |
| 60 | 6 | 35,651,584 | 16,832 | 180.0 | 7680×4320@30 |
| 61 | 6.1 | 35,651,584 | 16,832 | 240.0 | 7680×4320@60 |
| 62 | 6.2 | 35,651,584 | 16,832 | 480.0 | 7680×4320@120 |

VP9 has no tiers — single bitrate cap per level (unlike AV1/HEVC).

### vp9/decode.py (315 lines)
VP9 codec string parser with semantic validation. Uses `strip_hls_brands()` from hls.py.
Source: VP Codec ISO Media File Format Binding §5 (Codecs Parameter String).

| Line | Symbol | Description |
|------|--------|-------------|
| 25 | `_OPTIONAL_DEFAULTS` | Default values when optional fields omitted |
| 34 | `decode_vp9(codec_string)` | Main entry: parse + validate → result dict |
| 231 | `_validate_vp9(result, findings, level_obj)` | Validation checks |

**VP9 codec string format:**
```
vp09.<PP>.<LL>.<DD>[.<CC>.<cp>.<tc>.<mc>.<FF>]

Mandatory:  PP=profile, LL=level, DD=bitDepth (all 2-digit zero-padded)
Optional:   CC=chroma, cp=primaries, tc=transfer, mc=matrix, FF=range
            Must be ALL or NONE — partial optional fields are invalid.
Defaults:   CC=00, cp=01, tc=01, mc=01, FF=00
```

**VP9 Validation Checks:**
| Severity | Code | Trigger |
|----------|------|---------|
| error | VP9_ENTRY_UNKNOWN | Entry is not `vp09` |
| error | VP9_FIELD_COUNT | Not exactly 4 or 9 fields |
| error | VP9_FIELD_FORMAT | Non-2-digit field after entry |
| error | VP9_PROFILE_UNKNOWN | Profile not in {0, 1, 2, 3} |
| error | VP9_LEVEL_UNKNOWN | Level value not in defined set |
| error | VP9_DEPTH_INVALID | Bit depth not valid for profile or not in {8, 10, 12} |
| error | VP9_CHROMA_INVALID | CC value not valid for profile (full form only) |
| warning | VP9_DEPTH_12 | 12-bit (valid but rarely deployed) |
| warning | VP9_CP_TC_MISMATCH | PQ/HLG transfer with BT.709 primaries |
| info | VP9_SHORT_FORM | Using default optional values |
| info | VP9_BITRATE_CAP | Max bitrate for resolved level |
| info | VP9_COLOR_SPACE | Resolved color space summary |

VP9 standalone display format:
```
  ┌─ vp09.02.50.10.01.09.16.09.00
  │  Profile:  2 — Profile 2
  │  Level:    5 (value=50)
  │  Depth:    10-bit
  │  Chroma:   4:2:0 (CC=01, colocated/top-left)
  │  Color:    BT.2020 primaries, PQ transfer, BT.2020 NCL matrix
  │  Range:    Limited (studio swing)
  │  Bitrate:  ≤60 Mbps
  └─
```

---

## hevc/ Module (2,059 lines)

### hevc/profiles.py (353 lines)
13 HEVC profiles with constraint byte computation engine.

### hevc/levels.py (113 lines)
HEVC level table (1.0–6.2), 19 defined levels.

### hevc/decode.py (1,592 lines)
Full HEVC codec string decoder with 14 semantic checks. Uses `strip_hls_brands()` from hls.py.
Returns `findings` list, lowercase `family: "hevc"`, and `verdict` field.

---

## dv/ Module (826 lines)

### dv/profiles.py (345 lines)
10 DV compatibility entries. Profile 10 (AV1 base) at line 150.
`METADATA_DELIVERY` dict at line ~315 (shared by resolve.py and hybrid.py).

### dv/levels.py (145 lines)
DV level table + dual mapping to both HEVC and AV1 levels.

| Line | Symbol | Description |
|------|--------|-------------|
| 34 | `DV_LEVELS` | 13 DV levels with resolution/fps limits |
| 69 | `DV_TO_HEVC_LEVEL_IDC` | DV level → min HEVC level_idc |
| 87 | `DV_TO_AV1_LEVEL_IDX` | DV level → min AV1 seq_level_idx |

**DV → AV1 Level Mapping:**
| DV Lv | Res@fps | AV1 idx | AV1 Level |
|-------|---------|---------|-----------|
| 01 | 720p24 | 5 | 3.1 |
| 02 | 1080p24 | 8 | 4.0 |
| 03 | 1080p30 | 8 | 4.0 |
| 04 | 1080p60 | 9 | 4.1 |
| 05 | 2160p24 | 12 | 5.0 |
| 06 | 2160p30 | 12 | 5.0 |
| 07 | 2160p48 | 13 | 5.1 |
| 08 | 2160p60 | 13 | 5.1 |
| 09 | 2160p120 | 14 | 5.2 |
| 10 | 4320p24 | 16 | 6.0 |
| 11 | 4320p30 | 16 | 6.0 |
| 12 | 4320p48 | 17 | 6.1 |
| 13 | 4320p60 | 17 | 6.1 |

### dv/decode.py (335 lines)
DV codec string decoder (triplet/unified/brand formats). Uses `strip_hls_brands()` from hls.py.
Returns `findings` list with structured `{severity, code, message}` dicts, lowercase `family: "dv"`, and `verdict` field.

---

## Data Flow Diagrams

### Forward path: Content → codec strings
```
Content ─→ resolve.py
              ├─ _resolve_hevc() ─→ hevc/profiles → hevc/levels → hvc1.X.Y.LZZZ.BB
              ├─ _resolve_av1()  ─→ av1/profiles  → av1/levels  → av01.P.LLT.DD.M.CCC.cp.tc.mc.F
              ├─ _resolve_vp9()  ─→ vp9/profiles  → vp9/levels  → vp09.PP.LL.DD.CC.cp.tc.mc.FF
              └─ _resolve_dv()   ─→ dv/profiles   → dv/levels   → dvh1.PP.LL
```

### Reverse path: codec strings → decoded dicts
```
"hvc1.2.4.L153.B0"   ─→ decode_codec_string() ─→ decode_hevc()  ─→ {family:"hevc", findings:[], verdict:"VALID"}
"av01.0.13M.10"       ─→ decode_codec_string() ─→ decode_av1()   ─→ {family:"av1", findings:[], verdict:"VALID"}
"vp09.02.50.10"       ─→ decode_codec_string() ─→ decode_vp9()   ─→ {family:"vp9", findings:[], verdict:"VALID"}
"dav1.10.09"          ─→ decode_codec_string() ─→ decode_dv()    ─→ {family:"dv", findings:[], verdict:"VALID"}
```
Entry detection uses `CODEC_ENTRIES` from registry.py (no hardcoded if/elif).

### Hybrid path: "base, dv" → cross-validated result
```
"hvc1..., dvh1..."  ─→ decode_hybrid_string()
                          ├─ decode_hevc() + decode_dv()
                          └─ validate_hybrid()      ─→ {valid, issues[], notes[{severity,message}]}

"av01..., dav1..."  ─→ decode_hybrid_string()
                          ├─ decode_av1() + decode_dv()
                          └─ validate_av1_hybrid()  ─→ {valid, issues[], notes[{severity,message}]}
```

### Dependency graph (imports)
```
__init__.py ──→ models, resolve, hybrid, hevc.decode, av1.decode, vp9.decode, dv.decode
__main__.py ──→ models, resolve, hybrid, hevc.decode, dv.decode, display, tests, registry
registry.py ──→ (standalone, no imports)
resolve.py  ──→ models, hevc.profiles, hevc.levels, av1.profiles, av1.levels, vp9.profiles, vp9.levels, dv.profiles, dv.levels, hls
hybrid.py   ──→ models, hevc.decode, av1.decode, vp9.decode, av1.levels, dv.decode, dv.profiles, dv.levels, hls, registry
display.py  ──→ models, dv.levels

hevc/       ──→ models (NEVER imports dv/, av1/, or vp9/)
av1/        ──→ models (NEVER imports hevc/, dv/, or vp9/)
vp9/        ──→ models (NEVER imports hevc/, av1/, or dv/)
dv/         ──→ models (NEVER imports hevc/, av1/, or vp9/)
```

---

## Test Coverage (140 tests)

### Resolve tests (55) — `--test`
35 HEVC + 10 DV + 8 VP9 + 2 multi-codec/negative

### Decode tests (43) — `--decode-test`
- 17 HEVC (profiles, tiers, levels, constraint bytes, RExt, SCC, unified)
- 4 DV (P5, P9, P10, P20, P7 with layers)
- 12 AV1: valid short/full forms (P0/P1/P2), monochrome, level 31, errors (tier/mono/depth/brand)
- **10 VP9:** valid short/full forms (P0/P1/P2/P3), 12-bit, full range, errors (profile/depth/field count/chroma)

### Hybrid tests (17) — `--decode-test`
- 11 HEVC+DV (level paradox, codec mismatch, valid pairings)
- 6 AV1+DV: valid pair, brands (db4h/db1p), errors (8-bit/P1/wrong entry)

### Brand tests (8) — `--decode-test`
db4h, db1p, db2g, cdm4, unknown, no brand, HEVC+brand, hybrid+brand

### Roundtrip tests (17) — `--decode-test`
- 7 HEVC (resolve → decode → verify profile/level/tier)
- 2 DV (resolve → decode → verify)
- 4 AV1: 4K30 PQ, 1080p60 SDR, 8K30, 4K60 12-bit P2
- **4 VP9:** 1080p30 SDR, 4K HDR10, 8K30, 4K 4:2:2 P3

---

## Build History

| Batch | Description | Lines | Tests |
|-------|-------------|-------|-------|
| 0 | Monolith bootstrap | ~800 | 8 |
| 1 | RExt + constraint bytes | ~1,500 | 14 |
| 2 | Decoder + full constraint flags | ~2,500 | 30 |
| 3 | DV integration | ~3,200 | 42 |
| 4 | SCC/HT/Scalable/Multiview profiles | ~3,800 | 47 |
| 5 | Hybrid cross-validation | ~4,500 | 56 |
| 6 | Decode test suite + roundtrips | ~5,000 | 79 |
| 7 | HLS brands + package refactor | 5,648 | 96 |
| 8 | AV1 + dav1 full integration | 6,993 | 118 |
| 9 | v1.0.0: Phase 0 audit, schema normalization, registry, dedup, structured notes | 7,034 | 118 |
| **10** | **v1.1.0: VP9 codec family (4 profiles, 13 levels, decoder, resolver, display)** | **7,857** | **140** |

**v1.0.0 released 2026-02-23** — https://github.com/NoFear0411/codec-resolve

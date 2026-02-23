# CODEMAP.md — codec_resolve Package Reference
## 7,034 lines · 118 tests · zero dependencies
### Bidirectional: resolve ↔ decode ↔ validate ↔ hybrid
### Codec families: HEVC · AV1 · Dolby Vision (Profiles 5/7/8/9/10/20)

---

## Package Structure

```
codec_resolve/                    7,034 lines total
├── __init__.py          39       Public API re-exports
├── __main__.py         499       CLI: argparse, dispatch, help
├── models.py           284       Shared enums + dataclasses + H.273 color tables
├── registry.py          30       Codec entry point registry (FourCC → family)
├── hls.py              127       HLS brand registry + strip_hls_brands()
├── resolve.py          220       Master resolver (HEVC + AV1 + DV)
├── hybrid.py           817       Cross-validation + routing (structured notes)
├── display.py          613       Pretty-printers (standalone + hybrid)
├── tests.py            887       118 tests
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
└── dv/
    ├── __init__.py       1
    ├── profiles.py     345       10 DV compat entries + METADATA_DELIVERY
    ├── levels.py       145       DV level table + HEVC mapping + AV1 mapping
    └── decode.py       335       DV decoder (triplet/unified/brand)
```

**Architecture rule:** `hevc/`, `dv/`, and `av1/` are SIBLINGS — they never import each other.
`hybrid.py` is the ONLY bridge between codec families.

---

## Module Reference

### __init__.py (39 lines)
Public API re-exports.
```python
from codec_resolve import (
    resolve, decode_codec_string, decode_hybrid_string,
    decode_hevc, decode_av1, decode_dv,
    validate_hybrid, validate_av1_hybrid,
    Content, Chroma, Transfer, Gamut, Scan, Tier,
    ConstraintStyle, ResolvedCodec,
)
```

### __main__.py (499 lines)
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
python -m codec_resolve --test                                  # 47 resolve tests
python -m codec_resolve --decode-test                           # 71 decode/hybrid/brand/roundtrip tests
python -m codec_resolve --decode "av01.0.13M.10"                # AV1 standalone
python -m codec_resolve --decode "av01.0.13M.10, dav1.10.06"    # AV1+DV hybrid
python -m codec_resolve --codec av01 -r 4k --fps 60 -d 10 -c 420 -t pq -g bt2020
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

### registry.py (30 lines)
Codec entry point registry — single source of truth for FourCC → family dispatch.

| Line | Symbol | Description |
|------|--------|-------------|
| 3 | `CODEC_ENTRIES` | Dict: 8 FourCC entries → {family, base_codec, is_dv} |
| 14 | `ENTRY_ALIASES` | Dict: 6 alias groups (hevc, av1, dv, dv-avc, dv-av1, all) |
| 23 | `ALL_ENTRIES` | Set of all valid entry points |

**CODEC_ENTRIES:**
| Entry | Family | Base Codec | DV? |
|-------|--------|------------|-----|
| hvc1, hev1 | hevc | HEVC | No |
| av01 | av1 | AV1 | No |
| dvhe, dvh1 | dv | HEVC | Yes |
| dvav, dva1 | dv | AVC | Yes |
| dav1 | dv | AV1 | Yes |

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

### resolve.py (220 lines)
Master forward resolver: Content → codec string(s). Uses `METADATA_DELIVERY` from dv/profiles.py.

| Line | Symbol | Description |
|------|--------|-------------|
| 10 | `resolve(content, codecs)` | Main entry: dispatches to _resolve_hevc, _resolve_dv, _resolve_av1 |
| 33 | route `av01` | → `_resolve_av1(content, "av01")` |
| 48 | `_resolve_hevc(c, entry)` | HEVC forward resolve |
| 102 | `_resolve_dv(c, entry)` | DV forward resolve (uses METADATA_DELIVERY) |
| 158 | `_resolve_av1(c, entry)` | AV1 forward resolve: profile → level → tier → color → format_av1_string() |

### hybrid.py (817 lines)
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

### display.py (613 lines)
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
              └─ _resolve_dv()   ─→ dv/profiles   → dv/levels   → dvh1.PP.LL
```

### Reverse path: codec strings → decoded dicts
```
"hvc1.2.4.L153.B0"   ─→ decode_codec_string() ─→ decode_hevc()  ─→ {family:"hevc", findings:[], verdict:"VALID"}
"av01.0.13M.10"       ─→ decode_codec_string() ─→ decode_av1()   ─→ {family:"av1", findings:[], verdict:"VALID"}
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
__init__.py ──→ models, resolve, hybrid, hevc.decode, av1.decode, dv.decode
__main__.py ──→ models, resolve, hybrid, hevc.decode, dv.decode, display, tests, registry
registry.py ──→ (standalone, no imports)
resolve.py  ──→ models, hevc.profiles, hevc.levels, av1.profiles, av1.levels, dv.profiles, dv.levels, hls
hybrid.py   ──→ models, hevc.decode, av1.decode, av1.levels, dv.decode, dv.profiles, dv.levels, hls, registry
display.py  ──→ models, dv.levels

hevc/       ──→ models (NEVER imports dv/ or av1/)
av1/        ──→ models (NEVER imports hevc/ or dv/)
dv/         ──→ models (NEVER imports hevc/ or av1/)
```

---

## Test Coverage (118 tests)

### Resolve tests (47) — `--test`
36 HEVC + 5 DV + 4 DV validation + 2 multi-codec

### Decode tests (33) — `--decode-test`
- 17 HEVC (profiles, tiers, levels, constraint bytes, RExt, SCC, unified)
- 4 DV (P5, P9, P10, P20, P7 with layers)
- **12 AV1:** valid short/full forms (P0/P1/P2), monochrome, level 31, errors (tier/mono/depth/brand)

### Hybrid tests (17) — `--decode-test`
- 11 HEVC+DV (level paradox, codec mismatch, valid pairings)
- **6 AV1+DV:** valid pair, brands (db4h/db1p), errors (8-bit/P1/wrong entry)

### Brand tests (8) — `--decode-test`
db4h, db1p, db2g, cdm4, unknown, no brand, HEVC+brand, hybrid+brand

### Roundtrip tests (13) — `--decode-test`
- 7 HEVC (resolve → decode → verify profile/level/tier)
- 2 DV (resolve → decode → verify)
- **4 AV1:** 4K30 PQ, 1080p60 SDR, 8K30, 4K60 12-bit P2

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
| **9** | **v1.0.0: Phase 0 audit, schema normalization, registry, dedup, structured notes** | **7,034** | **118** |

**v1.0.0 released 2026-02-23** — https://github.com/NoFear0411/codec-resolve

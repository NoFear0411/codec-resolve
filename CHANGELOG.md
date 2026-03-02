# Changelog

## 1.4.0

Standardized decoder output across all 6 codec families.

### Standard Decoder Contract

Every `decode_*()` function now returns a consistent set of fields: `family`, `entry`, `entry_meaning`, `codec_string`, `codec_string_full`, `profile_idc`, `profile_name`, `level_idc`, `level_name`, `max_resolution`, `max_fps`, `bit_depth`, `chroma`, `max_bitrate_kbps`, `findings`, `verdict`. Family-specific fields are preserved alongside these.

### HEVC Migration

- **findings list:** Top-level `findings` list initialized early, constraint warnings bridged into it
- **Standard fields:** Added `level_name`, `max_fps`, `max_bitrate_kbps`, `max_resolution` (ASCII x, no labels)
- **Top-level depth/chroma:** Extracted `bit_depth` (int) and `chroma` (str) from stream_info strings
- **codec_string_full:** Always set (was only set when HLS brands present)

### Missing Fields Added

- **AV1:** `entry_meaning`, `profile_idc`, `level_idc`, `max_resolution`, `max_fps`, `max_bitrate_kbps`
- **VP9:** `entry_meaning`, `profile_idc`, `level_idc`, `max_resolution`, `max_fps`
- **AVC:** `max_fps`, `max_resolution` (fps suffix stripped, Unicode x normalized to ASCII)
- **DV:** `codec_string_full`, `level_idc`, `level_name`, `max_fps`, `max_bitrate_kbps`, `max_resolution`, `bit_depth` (int), `chroma`
- **VP8:** `entry_meaning`, `profile_idc`, `profile_name`, `level_idc`, `level_name`, `max_resolution`, `max_fps`, `max_bitrate_kbps`, verdict uppercase

### Display Helpers

- **`_format_bitrate(kbps)`:** Auto-scale Mbps/kbps with exact decimals, no rounding
- **`_print_validation(findings)`:** Shared validation section renderer replaces 6 inline copies
- **`_print_verdict(findings)`:** Shared verdict line renderer replaces 6 inline copies
- **`_print_hls_brands(d)`:** Shared HLS brand renderer replaces 3 inline copies
- Net display.py reduction: 748 → 679 lines

### Tests

- 180 tests: 61 resolve, 61 decode, 17 hybrid, 8 brand, 21 roundtrip, 12 contract
- **Contract tests:** 6 per-family tests verify all standard fields present with correct types
- **Bitrate formatter tests:** 6 edge cases (None, <1000, exact 1000, whole Mbps, fractional Mbps, large)

---

## 1.3.0

AVC/H.264 codec family support.

### Features
- **AVC forward resolve:** Content parameters → `avc1.PPCCLL` / `avc3.PPCCLL` (uppercase hex triplet)
- **AVC reverse decode:** Parse AVC codec strings with 11 validation codes (5 error, 1 warning, 5 info)
- **AVC constraint flags:** Full constraint_set0–5 flag parsing with reserved_zero_2bits validation
- **Derived profiles:** Constrained Baseline, Constrained High, Progressive High, Intra variants
- **Level 1b:** Dual encoding support (level_idc=11+set3 and level_idc=9)
- **Bitrate multipliers:** Per-profile MaxBR scaling (Baseline 1×, High 1.25×, High 10 3×, High 4:2:2/4:4:4 4×)

### Codecs
- **AVC:** 8 profiles (Baseline, Main, Extended, High, High 10, High 4:2:2, High 4:4:4 Predictive, CAVLC 4:4:4 Intra), 20 levels (1–6.2 + 1b), macroblock-based level selection

### Integration
- Registry: `avc1` and `avc3` entries + `avc` alias
- Hybrid routing: `decode_codec_string()` dispatches AVC automatically
- CLI: `--codec avc1`/`avc3` for forward resolve, `--decode "avc1.PPCCLL"` for reverse decode
- Public API: `decode_avc()` exported from `codec_resolve`

### Tests
- 168 tests: 61 forward-resolve (+6), 61 decode (+13), 17 hybrid, 8 brand, 21 roundtrip (+4)

---

## 1.2.1

Non-standard Dolby Vision FourCC support.

### Features
- **dvc1 recognition:** Deprecated pre-standard DV container tag, decoded and validated as Profile 5 HEVC
- **dvhp recognition:** OMAF/VR DV container tag (ISO/IEC 23090-2), decoded and validated as Profile 5 HEVC
- **DV_NONSTANDARD_ENTRY warning:** Both entries decode with a warning explaining their non-standard nature

### Integration
- Registry: `dvc1` and `dvhp` entries in `CODEC_ENTRIES`, added to `dv` alias
- Profile contracts: Both entries valid for Profile 5 only; `DV_ENTRY_MISMATCH` fires if used with other profiles
- Forward resolve: `--codec dvc1` and `--codec dvhp` supported
- Unified format: Embedded HEVC cross-validation works for both entries
- METADATA_DELIVERY: Delivery descriptions for both entries

### Tests
- 145 tests: 55 forward-resolve, 48 decode (+2 non-standard DV), 17 hybrid, 8 brand, 17 roundtrip

---

## 1.2.0

VP8 codec family support. License changed to AGPL-3.0.

### Features
- **VP8 reverse decode:** Validates bare `vp8` tag (case-insensitive, rejects suffixed forms like `vp08`)
- **VP8 display output:** Standalone pretty-print with fixed VP8 characteristics (8-bit, 4:2:0)

### Codecs
- **VP8:** Single bare tag — no profiles, no levels, no parameters (codec predates parameterized strings)

### Integration
- Registry: `vp8` entry in `CODEC_ENTRIES`
- Hybrid routing: `decode_codec_string()` dispatches VP8 automatically
- CLI: `--decode "vp8"` for reverse decode
- Public API: `decode_vp8()` exported from `codec_resolve`

### Changed
- **License:** LGPL-3.0 → AGPL-3.0-or-later (aligns with CodecProbe)

### Tests
- 143 tests: 55 forward-resolve, 46 decode (+3 VP8), 17 hybrid, 8 brand, 17 roundtrip

---

## 1.1.0

VP9 codec family support.

### Features
- **VP9 forward resolve:** Content parameters → `vp09.PP.LL.DD.CC.cp.tc.mc.FF` (full 9-field form)
- **VP9 reverse decode:** Parse VP9 codec strings (short 4-field and full 9-field forms) with 7 error codes, 1 warning, 3 info codes
- **VP9 profile selection:** 4 profiles via orthogonal bit-depth × chroma axes (P0/P1/P2/P3)
- **VP9 level resolution:** 13 levels (1–6.2) from pic_size × max_dim × sample_rate constraints
- **VP9 display output:** Standalone pretty-print with profile, level, chroma CC code, H.273 color names

### Codecs
- **VP9:** 4 profiles (Profile 0–3), 13 levels (1–6.2), chroma subsampling validation (CC field), H.273 color parameter support

### Integration
- Registry: `vp09` entry + `vp9` alias
- Hybrid routing: `decode_codec_string()` dispatches VP9 automatically
- CLI: `--codec vp09` for forward resolve, `--decode "vp09.XX.XX.XX"` for reverse decode
- Public API: `decode_vp9()` exported from `codec_resolve`

### Tests
- 140 tests: 55 forward-resolve (+8), 43 decode (+10), 17 hybrid, 8 brand, 17 roundtrip (+4)

---

## 1.0.0

Initial release.

### Features
- **Forward resolve:** Content parameters (resolution, fps, bit depth, chroma, transfer, gamut) to spec-correct codec strings
- **Reverse decode:** Parse HEVC, AV1, and Dolby Vision codec strings into every field with human-readable names
- **Hybrid cross-validation:** 30+ semantic checks for HEVC+DV and AV1+DV pairs (profile contract, level headroom, level paradox, entry sync, HLS brand validation, tier bitrate, fallback behavior)
- **HLS brand support:** `SUPPLEMENTAL-CODECS` brand parsing and cross-validation (db1p, db2g, db4h, cdm4)

### Codecs
- **HEVC:** 13 profiles (Main through MVRExt, SCC, HT, Scalable, Multiview), 19 levels (1.0-6.2), full constraint byte engine
- **AV1:** 3 profiles (Main, High, Professional), 14 levels (2.0-6.3), H.273 color parameter validation
- **Dolby Vision:** Profiles 5/7/8/9/10/20, 13 levels, bl_signal_compatibility_id sub-profiles (8.1/8.2/8.4)

### Tests
- 118 tests: 47 forward-resolve, 33 decode, 17 hybrid, 8 brand, 13 roundtrip

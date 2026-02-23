# Changelog

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

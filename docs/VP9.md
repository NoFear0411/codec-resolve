# VP9 Codec String Specification

Implementation reference for the `vp9/` module in codec_resolve.
All data verified against authoritative sources before coding.

## Sources

| Source | What it defines | URL |
|--------|----------------|-----|
| VP Codec ISO Media File Format Binding | Codec string format, field encoding | webmproject.org/vp9/mp4/ |
| VP9 Bitstream Specification | Profile definitions, level constraints | webmproject.org/vp9/levels/ |
| ITU-T H.273 | Color parameter tables (cp, tc, mc) | Shared with AV1 via `models.py` |
| CodecProbe v1 database | 21 real-world codec strings | Ground truth validation |

## Codec String Format

```
vp09.PP.LL.DD[.CC.cp.tc.mc.FF]
```

All fields are **2-digit zero-padded** integers. Dot-separated.

| Field | Pos | Description | Valid values |
|-------|-----|-------------|-------------|
| PP | 1 | Profile | 00, 01, 02, 03 |
| LL | 2 | Level (major×10 + minor) | 10, 20, 21, 30, 31, 40, 41, 50, 51, 52, 60, 61, 62 |
| DD | 3 | Bit depth | 08, 10, 12 |
| CC | 4 | Chroma subsampling | 00, 01, 02, 03 |
| cp | 5 | Colour primaries (H.273 Table 2) | 01–22 |
| tc | 6 | Transfer characteristics (H.273 Table 3) | 01–18 |
| mc | 7 | Matrix coefficients (H.273 Table 4) | 00–14 |
| FF | 8 | Video full range flag | 00 (limited), 01 (full) |

**Mandatory:** PP, LL, DD (positions 1–3).
**Optional:** CC through FF (positions 4–8). Must appear as a complete group — partial optional fields are invalid.

### Chroma Subsampling (CC)

| Value | Subsampling | chroma_sample_position |
|-------|-------------|----------------------|
| 00 | 4:2:0 | 0 (vertical / left) |
| 01 | 4:2:0 | 1 (colocated / top-left) |
| 02 | 4:2:2 | — |
| 03 | 4:4:4 | — |

Values 00 and 01 both represent 4:2:0 — they differ only in chroma sample position within the subsampled grid.

## Profiles

Source: VP9 Bitstream Specification §7.2.

| Profile | Bit Depth | Chroma Subsampling | CC values |
|---------|-----------|-------------------|-----------|
| 0 | 8 only | 4:2:0 only | 00, 01 |
| 1 | 8 only | 4:2:2 or 4:4:4 | 02, 03 |
| 2 | 10 or 12 | 4:2:0 only | 00, 01 |
| 3 | 10 or 12 | 4:2:2 or 4:4:4 | 02, 03 |

The two dimensions are orthogonal:
- **Bit depth axis:** Profiles 0+1 = 8-bit, Profiles 2+3 = high bit depth (10/12)
- **Chroma axis:** Profiles 0+2 = 4:2:0, Profiles 1+3 = non-4:2:0

Profile selection from content parameters:
```
profile = (depth > 8 ? 2 : 0) + (chroma != 4:2:0 ? 1 : 0)
```

## Level Table

Source: webmproject.org/vp9/levels/ (VP9 Bitstream Specification Annex A).

| Level | Value | MaxPicSize | MaxDim | MaxSampleRate | MaxBitrate (kbps) | MaxCPB (kbps) | MinCR | MaxTiles | Example |
|-------|-------|-----------|--------|---------------|------------------|--------------|-------|----------|---------|
| 1 | 10 | 36,864 | 512 | 829,440 | 200 | 400 | 2 | 1 | 256×144 @ 15 |
| 2 | 20 | 122,880 | 960 | 4,608,000 | 1,800 | 1,500 | 2 | 1 | 480×256 @ 30 |
| 2.1 | 21 | 245,760 | 1,344 | 9,216,000 | 3,600 | 2,800 | 2 | 2 | 640×384 @ 30 |
| 3 | 30 | 552,960 | 2,048 | 20,736,000 | 7,200 | 6,000 | 2 | 4 | 1080×512 @ 30 |
| 3.1 | 31 | 983,040 | 2,752 | 36,864,000 | 12,000 | 10,000 | 2 | 4 | 1280×768 @ 30 |
| 4 | 40 | 2,228,224 | 4,160 | 83,558,400 | 18,000 | 16,000 | 4 | 4 | 2048×1088 @ 30 |
| 4.1 | 41 | 2,228,224 | 4,160 | 160,432,128 | 30,000 | 18,000 | 4 | 4 | 2048×1088 @ 60 |
| 5 | 50 | 8,912,896 | 8,384 | 311,951,360 | 60,000 | 36,000 | 6 | 8 | 4096×2176 @ 30 |
| 5.1 | 51 | 8,912,896 | 8,384 | 588,251,136 | 120,000 | 46,000 | 8 | 8 | 4096×2176 @ 60 |
| 5.2 | 52 | 8,912,896 | 8,384 | 1,176,502,272 | 180,000 | — | 8 | 8 | 4096×2176 @ 120 |
| 6 | 60 | 35,651,584 | 16,832 | 1,176,502,272 | 180,000 | — | 8 | 16 | 8192×4352 @ 30 |
| 6.1 | 61 | 35,651,584 | 16,832 | 2,353,004,544 | 240,000 | — | 8 | 16 | 8192×4352 @ 60 |
| 6.2 | 62 | 35,651,584 | 16,832 | 4,706,009,088 | 480,000 | — | 8 | 16 | 8192×4352 @ 120 |

**No tiers.** VP9 has a single max bitrate per level (unlike AV1's Main/High tier split).

**No Level 0 in codec strings.** The ISOBMFF binding defines valid values as 10–62. The bitstream spec defines a Level 0 with constraints (MaxPicSize 36,864 / MaxBitrate 200 kbps / 256×144@15) but it is not representable in the codec string format.

**MaxCPB undefined for Levels 5.2+.** The spec marks these as TBD.

### Level Resolution from Content

The forward resolver selects the minimum level whose constraints satisfy the content:
1. `width × height ≤ MaxPicSize`
2. `max(width, height) ≤ MaxDim`
3. `width × height × fps ≤ MaxSampleRate`

## Validation Rules

### Errors (reject string)

| Code | Condition |
|------|-----------|
| `VP9_PROFILE_UNKNOWN` | Profile not in {0, 1, 2, 3} |
| `VP9_LEVEL_UNKNOWN` | Level value not in {10, 20, 21, 30, 31, 40, 41, 50, 51, 52, 60, 61, 62} |
| `VP9_DEPTH_INVALID` | Bit depth incompatible with profile: P0/P1 require 8, P2/P3 require 10 or 12 |
| `VP9_CHROMA_INVALID` | Chroma incompatible with profile: P0/P2 require 4:2:0 (CC 00/01), P1/P3 require non-4:2:0 (CC 02/03) |
| `VP9_FIELD_COUNT` | Must have exactly 4 fields (short) or 9 fields (full). Partial optional fields are invalid. |
| `VP9_FIELD_FORMAT` | Non-numeric field or wrong digit count (all fields are 2-digit) |
| `VP9_ENTRY_UNKNOWN` | Entry point is not `vp09` |

### Warnings

| Code | Condition |
|------|-----------|
| `VP9_DEPTH_12` | 12-bit content — valid per spec but rarely deployed in practice |

### Info

| Code | Condition |
|------|-----------|
| `VP9_SHORT_FORM` | Using default color values (only mandatory fields present) |
| `VP9_COLOR_SPACE` | Resolved color primaries / transfer / matrix summary |
| `VP9_BITRATE_CAP` | Max bitrate for this level |

## Differences from AV1

| Aspect | VP9 | AV1 |
|--------|-----|-----|
| Entry point | `vp09` | `av01` |
| Tiers | None | Main / High |
| Mono flag | None | `mono_chrome` field |
| Chroma encoding | 2-digit CC (00–03) | 3-digit CCC (subsampling_x, subsampling_y, CSP) |
| Level encoding | major×10 + minor (10–62) | seq_level_idx (0–23) |
| DV hybrid | Not supported | Profile 10 via `dav1` |
| Color field widths | All 2-digit | 2–3 digit mixed |

## Ground Truth — CodecProbe v1 Strings

These codec strings are tested against real browser APIs in production. They serve as the primary validation corpus for the decoder.

### Short form (mandatory only)
```
vp09.00.10.08     P0  Level 1    8-bit   4:2:0
vp09.00.21.08     P0  Level 2.1  8-bit   4:2:0
vp09.00.31.08     P0  Level 3.1  8-bit   4:2:0
vp09.01.10.08     P1  Level 1    8-bit   4:2:2/4:4:4
vp09.01.31.08     P1  Level 3.1  8-bit   4:2:2/4:4:4
vp09.02.10.10     P2  Level 1    10-bit  4:2:0
vp09.02.31.10     P2  Level 3.1  10-bit  4:2:0
vp09.03.10.10     P3  Level 1    10-bit  4:2:2/4:4:4
vp09.03.31.10     P3  Level 3.1  10-bit  4:2:2/4:4:4
```

### Full form (with color parameters)
```
vp09.02.10.10.01.09.16.09.01   P2 HDR10:  4:2:0 colocated, BT.2020, PQ, full range
vp09.02.10.10.01.09.18.09.01   P2 HLG:   4:2:0 colocated, BT.2020, HLG, full range
```

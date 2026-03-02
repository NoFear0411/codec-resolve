"""
Pretty-print functions for resolved and decoded codec results.
"""
from typing import List
from .models import Content, ResolvedCodec
from .dv.levels import DV_LEVEL_LOOKUP


# ─── Shared Display Helpers ────────────────────────────────────────────
# Used by per-family print_decoded blocks and print_hybrid.


def _format_bitrate(kbps):
    """Format bitrate with auto-scaling. Exact decimals, no rounding."""
    if kbps is None:
        return None
    if kbps >= 1000:
        mbps = kbps / 1000
        if mbps == int(mbps):
            return f"{int(mbps)} Mbps"
        s = f"{mbps:.3f}".rstrip("0")
        return f"{s} Mbps"
    return f"{kbps:,} kbps"


def _print_validation(findings, prefix="  │"):
    """Print the validation section from a findings list."""
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]
    if not (errors or warnings or infos):
        return
    print(f"{prefix}")
    print(f"{prefix}  Validation:")
    for f in errors:
        print(f"{prefix}    ✗ [{f['code']}] {f['message']}")
        if f.get("recommendation"):
            print(f"{prefix}      → {f['recommendation']}")
    for f in warnings:
        print(f"{prefix}    ⚠ [{f['code']}] {f['message']}")
        if f.get("recommendation"):
            print(f"{prefix}      → {f['recommendation']}")
    for f in infos:
        print(f"{prefix}    ℹ [{f['code']}] {f['message']}")
        if f.get("recommendation"):
            print(f"{prefix}      → {f['recommendation']}")


def _print_verdict(findings, prefix="  │"):
    """Print the verdict line from a findings list."""
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    print(f"{prefix}")
    if errors:
        print(f"{prefix}  ╸ Verdict: ✗ INVALID — "
              f"{len(errors)} error{'s' if len(errors) != 1 else ''}"
              f"{f', {len(warnings)} warning' + ('s' if len(warnings) != 1 else '') if warnings else ''}")
    elif warnings:
        print(f"{prefix}  ╸ Verdict: ⚠ VALID with "
              f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
    else:
        print(f"{prefix}  ╸ Verdict: ✓ VALID")


def _print_hls_brands(d, prefix="  │"):
    """Print HLS brand section if present."""
    if not d.get("hls_brands"):
        return
    print(f"{prefix}")
    print(f"{prefix}  HLS Brand:")
    for bi in d["hls_brands"]:
        print(f"{prefix}    /{bi['brand']} — {bi['description']}")
        if bi.get("video_range"):
            print(f"{prefix}    VIDEO-RANGE: {bi['video_range']}")


def print_results(content: Content, results: List[ResolvedCodec],
                  verbose: bool = True):
    """Pretty-print the resolved codec strings."""
    if verbose:
        print(f"\n  Content: {content.describe()}")
        print()

    for r in results:
        print(f"  {r.codec_string}")
        if verbose:
            print(f"    ├─ Family:  {r.family.upper()}")
            print(f"    ├─ Profile: {r.profile_name}")
            print(f"    ├─ Level:   {r.level_name}")
            if r.tier_name:
                print(f"    ├─ Tier:    {r.tier_name}")
            for i, note in enumerate(r.notes):
                connector = "└─" if i == len(r.notes) - 1 else "├─"
                print(f"    {connector} {note}")
            print()

    # If we have both HEVC and DV results, show hybrid
    hevc_results = [r for r in results if r.family == "hevc"]
    dv_results = [r for r in results if r.family == "dv"]
    if hevc_results and dv_results:
        hevc_r = hevc_results[0]
        dv_r = dv_results[0]
        hybrid_str = f"{hevc_r.codec_string}, {dv_r.codec_string}"

        if verbose:
            print(f"  ─── HLS Hybrid ───────────────────────────────────")
            print(f"  {hybrid_str}")
            print()

            # Cross-validate by decoding, enriching DV with resolved bl_compat
            try:
                result = decode_hybrid_string(hybrid_str)
                # Enrich DV decode with bl_compat_id from resolve (not in string).
                # The resolved DV profile carries the exact bl_compat_id, but the
                # codec string format doesn't encode it. Inject it back for accurate
                # cross-validation notes.
                if dv_r.family == "dv":
                    # Extract bl_compat_id directly from the resolved profile object.
                    # DV codec string format: dvh1.PP.LL — profile_idc is in the string
                    # but bl_compat_id is only in the RPU. We match by profile IDC.
                    resolved_dv_profile = dv_r.profile_name
                    # Map known resolve profile names → bl_compat_id
                    # This replaces the old fragile substring search against DV_COMPAT keys
                    compat_from_name = {
                        "DV Profile 8.1 (HDR10-Compat)": 1,
                        "DV Profile 8.2 (SDR-Compat)": 2,
                        "DV Profile 8.4 (HLG-Compat)": 4,
                        "DV Profile 8 (no standard fallback)": 0,
                        "DV Profile 8 (bl_compat=0)": 0,
                    }
                    bl_cid = compat_from_name.get(resolved_dv_profile)
                    if bl_cid is not None:
                        result["dv"]["bl_compat_id"] = bl_cid
                        # Re-validate with known bl_compat
                        result["validation"] = validate_hybrid(
                            result["hevc"], result["dv"])

                val = result["validation"]
                status = "✓ Valid pairing" if val["valid"] else "✗ Invalid pairing"
                print(f"    {status}")
                for issue in val["issues"]:
                    print(f"    ✗ {issue}")
                _NOTE_PREFIX = {"pass": "✓ ", "warning": "⚠ ", "info": "ℹ ", "note": ""}
                for note in val["notes"]:
                    pfx = _NOTE_PREFIX.get(note["severity"], "")
                    print(f"    {pfx}{note['message']}")

                compat = val.get("compat")
                if compat and compat.fallback_format:
                    print(f"    Non-DV fallback: {compat.fallback_format}")
            except ValueError:
                pass  # If decode fails, skip hybrid analysis
            print()


def print_bare(results: List[ResolvedCodec]):
    """Print just the codec strings, one per line."""
    for r in results:
        print(r.codec_string)
    # Also print hybrid if both families present
    hevc = [r for r in results if r.family == "hevc"]
    dv = [r for r in results if r.family == "dv"]
    if hevc and dv:
        print(f"{hevc[0].codec_string}, {dv[0].codec_string}")


# =============================================================================
# SELF-TEST
# =============================================================================


def print_hybrid(result: dict):
    """Pretty-print a decoded hybrid codec pair (HEVC+DV or AV1+DV)."""
    # Detect base layer type
    is_av1 = "av1" in result
    base = result.get("av1") or result["hevc"]
    dv = result["dv"]
    val = result["validation"]

    # Count all issues for overall status
    base_findings = base.get("findings", [])
    base_errors = [f for f in base_findings if f["severity"] == "error"]
    base_warnings = [f for f in base_findings if f["severity"] == "warning"]
    cross_invalid = not val["valid"]

    overall_invalid = cross_invalid or len(base_errors) > 0
    status = "✗ INVALID" if overall_invalid else (
        "⚠ VALID with warnings" if base_warnings else "✓ VALID")

    print(f"\n  ╔══ HLS Hybrid Codec: {val['hybrid_string']}")
    print(f"  ║  Status: {status}")
    print(f"  ║")

    if is_av1:
        # ── AV1 Base Layer ───────────────────────────────────
        av1_prof = f"{base['seq_profile']} ({base['profile_name']})"
        av1_lvl = base.get("level_name", "?")
        av1_tier = "Main" if base.get("tier", 0) == 0 else "High"
        print(f"  ║  ┌─ AV1 Base Layer: {base['codec_string']}")
        print(f"  ║  │  Profile:  {av1_prof}")
        print(f"  ║  │  Level:    {av1_lvl} / {av1_tier} tier")
        print(f"  ║  │  Depth:    {base.get('bit_depth', '?')}-bit")
        cp = base.get("color_primaries_name", "")
        tc = base.get("transfer_characteristics_name", "")
        if cp and tc:
            print(f"  ║  │  Color:    {cp} / {tc}")
    else:
        # ── HEVC Base Layer ──────────────────────────────────
        hevc = base
        hevc_prof = f"{hevc['profile_idc']} ({hevc['profile_name']})"
        hevc_lvl = hevc.get("level_number", "?")
        hevc_tier = hevc.get("tier_name", "?")
        si = hevc.get("stream_info", {})
        print(f"  ║  ┌─ HEVC Base Layer: {hevc['codec_string']}")
        print(f"  ║  │  Profile:  {hevc_prof}")
        if "rext_sub_profile" in hevc:
            print(f"  ║  │  RExt sub: {hevc['rext_sub_profile']}")
        if "scc_sub_profile" in hevc:
            print(f"  ║  │  SCC sub:  {hevc['scc_sub_profile']}")
        print(f"  ║  │  Level:    {hevc_lvl} / {hevc_tier} tier")
        if "level_max_resolution" in hevc:
            print(f"  ║  │  Max res:  {hevc['level_max_resolution']}")
        if "level_max_bitrate_label" in hevc:
            print(f"  ║  │  Max rate: {hevc['level_max_bitrate_label']}")
        if si:
            depth = si.get("bit_depth", "?")
            chroma = si.get("chroma", "?")
            print(f"  ║  │  Stream:   {depth}, {chroma}")

    # Surface base layer validation findings within hybrid view
    if base_errors or base_warnings:
        print(f"  ║  │")
        base_label = "AV1" if is_av1 else "HEVC"
        print(f"  ║  │  {base_label} validation:")
        for f in base_errors:
            print(f"  ║  │    ✗ [{f['code']}] {f['message']}")
        for f in base_warnings:
            print(f"  ║  │    ⚠ [{f['code']}] {f['message']}")

    base_infos = [f for f in base_findings if f["severity"] == "info"]
    if base_infos:
        for f in base_infos:
            print(f"  ║  │    ℹ {f['message']}")

    print(f"  ║  └─")
    print(f"  ║")

    # ── DV Supplement ────────────────────────────────────
    print(f"  ║  ┌─ Dolby Vision Supplement: {dv['codec_string']}")
    print(f"  ║  │  Profile:  {dv['profile_idc']} — {dv['profile_name']}")
    if "sub_profiles" in dv:
        for sp, desc in dv["sub_profiles"].items():
            print(f"  ║  │    {sp}: {desc}")
        if "note" in dv:
            print(f"  ║  │    ℹ {dv['note']}")
    if dv.get("enhancement_layer") is not None:
        el = ("Present (dual-layer)" if dv["enhancement_layer"]
              else "None (single-layer + RPU)")
        print(f"  ║  │  EL:       {el}")
    if "level_max_resolution" in dv:
        print(f"  ║  │  Level:    {dv['level_id']:02d} "
              f"— {dv['level_max_resolution']}")
    elif "level_id" in dv:
        lv = DV_LEVEL_LOOKUP.get(dv["level_id"])
        if lv:
            print(f"  ║  │  Level:    {dv['level_id']:02d} "
                  f"— ≤{lv.max_width}×{lv.max_height}@{lv.max_fps:g}fps")
    print(f"  ║  └─")

    # ── Cross-validation ─────────────────────────────────
    print(f"  ║")
    print(f"  ║  Cross-validation:")
    if val["issues"]:
        for issue in val["issues"]:
            print(f"  ║    ✗ {issue}")
    _NOTE_PREFIX = {"pass": "✓ ", "warning": "⚠ ", "info": "ℹ ", "note": ""}
    for note in val["notes"]:
        pfx = _NOTE_PREFIX.get(note["severity"], "")
        print(f"  ║    {pfx}{note['message']}")

    # ── Fallback Behavior ────────────────────────────────
    compat = val.get("compat")
    if compat:
        print(f"  ║")
        print(f"  ║  Fallback behavior:")
        if not compat.fallback_format:
            print(f"  ║    DV decoder required — no standard fallback")
            if compat.colorspace == "IPTPQc2":
                print(f"  ║    ⚠ IPTPQc2 closed-loop: standard decoders "
                      f"produce color distortion")
        else:
            print(f"  ║    DV-capable:     Full Dolby Vision rendering")
            print(f"  ║    Non-DV player:  {compat.fallback_format}")
            if compat.fallback_type == "signaled":
                print(f"  ║    Fallback mode:  Signaled "
                      f"(bl_signal_compatibility_id in RPU)")
            elif compat.fallback_type == "hardware":
                print(f"  ║    Fallback mode:  Hardware "
                      f"(player strips RPU, decodes BL directly)")
        print(f"  ║")
        print(f"  ║  Layer structure:   {compat.layer_structure}")
        print(f"  ║  Metadata delivery: "
              f"{'dvh1=out-of-band (HLS/MP4) / dvhe=in-band (DASH/TS)'}")

    # ── Combined Verdict ─────────────────────────────────
    total_errors = len(base_errors) + len(val["issues"])
    total_warnings = len(base_warnings)
    print(f"  ║")
    if total_errors > 0:
        print(f"  ║  ╸ Verdict: ✗ INVALID — "
              f"{total_errors} error{'s' if total_errors != 1 else ''}"
              f"{f', {total_warnings} warning' + ('s' if total_warnings != 1 else '') if total_warnings else ''}")
    elif total_warnings > 0:
        print(f"  ║  ╸ Verdict: ⚠ VALID with "
              f"{total_warnings} warning{'s' if total_warnings != 1 else ''}")
    else:
        print(f"  ║  ╸ Verdict: ✓ VALID")
    print(f"  ║")
    print(f"  ╚══")


def print_decoded(d: dict):
    """Pretty-print a decoded codec string with validation summary."""
    display_str = d.get("codec_string_full", d["codec_string"])
    print(f"\n  ┌─ {display_str}")
    print(f"  │")
    print(f"  │  Family:   {d['family']}")
    entry_meaning = d.get('entry_meaning', '')
    if entry_meaning:
        print(f"  │  Entry:    {d['entry']}  ({entry_meaning})")
    else:
        print(f"  │  Entry:    {d['entry']}")

    if d["family"] == "av1":
        # ── AV1 Profile ─────────────────────────────────────
        print(f"  │")
        print(f"  │  Profile:  {d['seq_profile']} — {d['profile_name']}")
        print(f"  │  Level:    {d['level_name']} / "
              f"{'Main' if d['tier'] == 0 else 'High'} tier")
        print(f"  │  Depth:    {d['bit_depth']}-bit")

        # ── Color Parameters ─────────────────────────────────
        chroma_label = d.get('chroma_name', d.get('chroma', '?'))
        if d.get('monochrome'):
            chroma_label = "Monochrome"
        print(f"  │  Chroma:   {chroma_label} "
              f"(subsampling {d.get('subsampling_x','?')},"
              f"{d.get('subsampling_y','?')} "
              f"position {d.get('chroma_sample_position','?')})")

        cp_name = d.get('color_primaries_name', '?')
        tc_name = d.get('transfer_characteristics_name', '?')
        mc_name = d.get('matrix_coefficients_name', '?')
        print(f"  │  Color:    {cp_name} primaries, "
              f"{tc_name} transfer, {mc_name} matrix")
        print(f"  │  Range:    {d.get('video_range_name', '?')}")

        if d.get('max_bitrate_kbps'):
            br_label = _format_bitrate(d['max_bitrate_kbps'])
            bpf = d.get('bitrate_profile_factor', 1.0)
            tier_label = 'Main' if d['tier'] == 0 else 'High'
            print(f"  │  Bitrate:  ≤{br_label} "
                  f"({tier_label} tier × P{d['seq_profile']} factor {bpf}×)")

        if not d.get('has_optional_fields'):
            print(f"  │")
            print(f"  │  ℹ Short form — optional color fields use defaults")

        _print_validation(d.get("findings", []))
        _print_hls_brands(d)
        _print_verdict(d.get("findings", []))

    elif d["family"] == "hevc":
        # ── Profile ──────────────────────────────────────────
        print(f"  │")
        print(f"  │  Profile:  {d['profile_idc']} — {d['profile_name']}")
        if d["profile_space"] != 0:
            print(f"  │  Space:    {d['profile_space_name']}")
        if "rext_sub_profile" in d:
            print(f"  │  RExt sub: {d['rext_sub_profile']}")
        if "scc_sub_profile" in d:
            print(f"  │  SCC sub:  {d['scc_sub_profile']}")
        if "profile_max_depth" in d:
            print(f"  │  Spec:     {d['profile_max_depth']}, "
                  f"{d['profile_chroma_support']}")
        if "profile_note" in d:
            print(f"  │  Purpose:  {d['profile_note']}")

        # ── Level & Tier ─────────────────────────────────────
        print(f"  │  Level:    {d.get('level_number', '?')} "
              f"(level_idc={d['level_idc']})")
        print(f"  │  Tier:     {d['tier_name']}")
        if "level_max_resolution" in d:
            print(f"  │  Max res:  {d['level_max_resolution']}")
        if "level_max_bitrate_label" in d:
            br_label = d['level_max_bitrate_label']
            # RExt factor label already includes tier info
            if "RExt" in br_label or "CpbBrVclFactor" in br_label:
                print(f"  │  Max rate: {br_label}")
            else:
                print(f"  │  Max rate: {br_label} "
                      f"({d['tier_name']} tier)")

        # ── Backward Compatibility ───────────────────────────
        if d.get("compatible_with_profiles"):
            print(f"  │")
            print(f"  │  Backward-compatible with:")
            for cp in d["compatible_with_profiles"]:
                print(f"  │    • {cp}")

        # ── Stream Characteristics ───────────────────────────
        si = d.get("stream_info", {})
        if si:
            print(f"  │")
            print(f"  │  Stream characteristics:")
            print(f"  │    Scan:        {si.get('scan', '—')}")
            print(f"  │    Frame only:  {si.get('frame_only', '—')}")
            print(f"  │    Bit depth:   {si.get('bit_depth', '—')}")
            print(f"  │    Chroma:      {si.get('chroma', '—')}")
            print(f"  │    Lower BR:    {si.get('lower_bit_rate', '—')}")
            if "one_picture_only" in si:
                print(f"  │    Still image: {si['one_picture_only']}")
            if "inbld" in si:
                print(f"  │    INBLD:       {si['inbld']}")
            if "intra_only" in si:
                print(f"  │    Intra-only:  {si['intra_only']}")
            if "precision_gate" in si:
                print(f"  │")
                print(f"  │  Precision Gate (Byte 2):")
                print(f"  │    {si['precision_gate']}")
            if "scc_tools" in si:
                print(f"  │")
                print(f"  │  SCC Tools (Byte 3):")
                for tool, status in si["scc_tools"].items():
                    print(f"  │    {tool.upper():8s} {status}")

        # ── Constraint Style ─────────────────────────────────
        # (displayed with constraint bytes below)

        # ── Constraint Byte Warnings (malformed input) ───────
        if "constraint_warnings" in d:
            print(f"  │")
            for warn in d["constraint_warnings"]:
                print(f"  │  ⚠ Parse: {warn}")

        _print_validation(d.get("findings", []))

        # ── Raw Constraint Bytes ─────────────────────────────
        n_present = d.get("constraint_bytes_present", 0)
        if n_present > 0:
            raw = d["constraint_bytes_raw"][:n_present]
            print(f"  │")
            print(f"  │  Constraint bytes ({n_present}): "
                  f"{' '.join(raw)}")
            if "constraint_style" in d:
                print(f"  │    Style:     {d['constraint_style']}")

            # Bit-level breakdown
            flags = d.get("constraint_flags", {})
            set_flags = [f for f, v in flags.items()
                         if v and not f.startswith("reserved")]
            clear_flags = [f for f, v in flags.items()
                           if not v and not f.startswith("reserved")]
            if set_flags:
                print(f"  │    Set (=1):   {', '.join(set_flags)}")
            if clear_flags:
                print(f"  │    Clear (=0): {', '.join(clear_flags)}")

        _print_hls_brands(d)
        _print_verdict(d.get("findings", []))

    elif d["family"] == "dv":
        print(f"  │  BL codec: {d.get('base_layer_codec', '—')}")
        print(f"  │")
        print(f"  │  Profile:  {d['profile_idc']} — {d['profile_name']}")
        if "sub_profiles" in d:
            for sp, desc in d["sub_profiles"].items():
                print(f"  │    {sp}: {desc}")
            if "note" in d:
                print(f"  │    ℹ {d['note']}")
        else:
            for key in ("base_layer_profile", "transfer_function",
                        "color_gamut", "bit_depth"):
                if key in d:
                    label = key.replace("_", " ").title()
                    print(f"  │    {label}: {d[key]}")
        if "colorspace" in d:
            print(f"  │  Color:    {d['colorspace']}")
        if "layer_detail" in d:
            print(f"  │  Layers:   {d['layer_detail']}")
        if "enhancement_layer" in d:
            print(f"  │  EL:       {'Present (dual-layer)' if d['enhancement_layer'] else 'None (single-layer + RPU)'}")
        if "cross_compat" in d:
            print(f"  │  Cross:    {d['cross_compat']}")
        # Structured findings (inline, before status)
        dv_findings = d.get("findings", [])
        for f in dv_findings:
            if f["severity"] == "error":
                print(f"  │  ✗ [{f['code']}] {f['message']}")
            elif f["severity"] == "warning":
                print(f"  │  ⚠ [{f['code']}] {f['message']}")
        if "status" in d:
            print(f"  │  Status:   {d['status']}")

        print(f"  │")
        print(f"  │  Level:    {d.get('level_id', '?'):02d}")
        if "level_max_resolution" in d:
            print(f"  │  Max cap:  {d['level_max_resolution']}")
        if "level_max_bitrate_main" in d:
            print(f"  │  Max rate: {d['level_max_bitrate_main']} (Main)")
        if "level_max_bitrate_high" in d:
            print(f"  │            {d['level_max_bitrate_high']} (High)")

        # ── HLS Brands (SUPPLEMENTAL-CODECS) ─────────────────
        if d.get("hls_brands"):
            print(f"  │")
            print(f"  │  HLS Brand:")
            for bi in d["hls_brands"]:
                print(f"  │    /{bi['brand']} — {bi['description']}")
                if bi.get("video_range"):
                    print(f"  │    VIDEO-RANGE: {bi['video_range']}")
            if d.get("brand_inferred_subprofile"):
                print(f"  │    → Inferred: Profile "
                      f"{d['brand_inferred_subprofile']}")
            if d.get("brand_findings"):
                for bf in d["brand_findings"]:
                    sev = {"info": "ℹ", "warning": "⚠", "error": "✗"}
                    print(f"  │    {sev.get(bf['severity'], '?')} "
                          f"[{bf['code']}] {bf['message']}")

        _print_verdict(dv_findings)

        # ── Unified Format: Embedded HEVC ──────────────────
        if d.get("unified_format"):
            print(f"  │")
            print(f"  │  ═══ Unified Format Detected ═══")
            print(f"  │  Reconstructed HEVC: "
                  f"{d.get('embedded_hevc_string', '?')}")

            if "embedded_hevc" in d:
                eh = d["embedded_hevc"]
                si = eh.get("stream_info", {})
                print(f"  │")
                print(f"  │  ┌─ Embedded HEVC Base Layer")
                print(f"  │  │  Profile:  {eh.get('profile_idc')} "
                      f"({eh.get('profile_name', '?')})")
                print(f"  │  │  Level:    {eh.get('level_number', '?')} "
                      f"/ {eh.get('tier_name', '?')} tier")
                if "level_max_resolution" in eh:
                    print(f"  │  │  Max res:  {eh['level_max_resolution']}")
                if "level_max_bitrate_label" in eh:
                    print(f"  │  │  Max rate: "
                          f"{eh['level_max_bitrate_label']}")
                if si:
                    print(f"  │  │  Stream:   "
                          f"{si.get('bit_depth', '?')}, "
                          f"{si.get('chroma', '?')}")

                # Surface HEVC validation findings (Gap A fix)
                eh_findings = eh.get("findings", [])
                eh_errors = [f for f in eh_findings
                             if f["severity"] == "error"]
                eh_warns = [f for f in eh_findings
                            if f["severity"] == "warning"]
                if eh_errors or eh_warns:
                    print(f"  │  │")
                    print(f"  │  │  HEVC validation:")
                    for f in eh_errors:
                        print(f"  │  │    ✗ [{f['code']}] "
                              f"{f['message']}")
                    for f in eh_warns:
                        print(f"  │  │    ⚠ [{f['code']}] "
                              f"{f['message']}")

                print(f"  │  └─")

            if "embedded_validation" in d:
                v = d["embedded_validation"]
                print(f"  │")
                print(f"  │  Cross-validation:")
                for issue in v.get("issues", []):
                    print(f"  │    ✗ {issue}")
                _NOTE_PREFIX = {"pass": "✓ ", "warning": "⚠ ", "info": "ℹ ", "note": ""}
                for note in v.get("notes", []):
                    pfx = _NOTE_PREFIX.get(note["severity"], "")
                    print(f"  │    {pfx}{note['message']}")

                verdict = ("✓ VALID" if v.get("valid", False)
                           else f"✗ INVALID — "
                                f"{len(v.get('issues', []))} error"
                                f"{'s' if len(v.get('issues', [])) != 1 else ''}")
                print(f"  │")
                print(f"  │  ╸ Hybrid verdict: {verdict}")

            if "embedded_hevc_error" in d:
                print(f"  │")
                print(f"  │  ✗ HEVC decode error: "
                      f"{d['embedded_hevc_error']}")

    elif d["family"] == "vp9":
        # ── VP9 Profile ────────────────────────────────────────
        print(f"  │")
        print(f"  │  Profile:  {d['profile']} — {d['profile_name']}")
        print(f"  │  Level:    {d['level_name']} (value={d['level_value']})")
        print(f"  │  Depth:    {d['bit_depth']}-bit")

        # ── Color Parameters ───────────────────────────────────
        chroma_label = d.get('chroma_name', '?')
        if d.get('chroma_sample_position') is not None:
            csp_name = d.get('chroma_sample_position_name', '')
            chroma_label += f" (CC {d['chroma_subsampling']:02d}: {csp_name})"
        print(f"  │  Chroma:   {chroma_label}")

        cp_name = d.get('color_primaries_name', '?')
        tc_name = d.get('transfer_characteristics_name', '?')
        mc_name = d.get('matrix_coefficients_name', '?')
        print(f"  │  Color:    {cp_name} primaries, "
              f"{tc_name} transfer, {mc_name} matrix")
        print(f"  │  Range:    {d.get('video_range_name', '?')}")

        if d.get('max_bitrate_kbps'):
            br_label = _format_bitrate(d['max_bitrate_kbps'])
            print(f"  │  Bitrate:  ≤{br_label} (no tiers)")

        if not d.get('has_optional_fields'):
            print(f"  │")
            print(f"  │  ℹ Short form — optional color fields use defaults")

        _print_validation(d.get("findings", []))
        _print_verdict(d.get("findings", []))

    elif d["family"] == "avc":
        # ── AVC/H.264 Profile ──────────────────────────────────
        print(f"  │")
        print(f"  │  Profile:  {d['profile_idc']} — {d['profile_name']}")
        if d.get("constrained_profile"):
            print(f"  │  Derived:  {d['constrained_profile']}")
        print(f"  │  Level:    {d.get('level_name', '?')} "
              f"(level_idc={d['level_idc']})")
        if "level_max_resolution" in d:
            print(f"  │  Max res:  {d['level_max_resolution']}")
        if "bit_depth" in d:
            print(f"  │  Depth:    {d['bit_depth']}-bit")
        if "chroma" in d:
            print(f"  │  Chroma:   {d['chroma']}")

        # ── Constraints ────────────────────────────────────────
        cb = d.get("constraint_byte", 0)
        flags = d.get("constraint_flags", {})
        set_flags = [name for name, val in flags.items() if val]
        if set_flags:
            print(f"  │  Flags:    {', '.join(set_flags)} "
                  f"(0x{cb:02X})")
        else:
            print(f"  │  Flags:    none (0x{cb:02X})")

        if d.get("max_bitrate_kbps"):
            br_label = _format_bitrate(d['max_bitrate_kbps'])
            print(f"  │  Bitrate:  ≤{br_label}")

        _print_validation(d.get("findings", []))
        _print_hls_brands(d)
        _print_verdict(d.get("findings", []))

    elif d["family"] == "vp8":
        # ── VP8 (bare tag, fixed capabilities) ────────────────
        print(f"  │")
        print(f"  │  Codec:    {d.get('codec_name', 'VP8')}")
        print(f"  │  Depth:    {d.get('bit_depth', 8)}-bit")
        print(f"  │  Chroma:   {d.get('chroma', '4:2:0')}")

        _print_validation(d.get("findings", []))
        _print_verdict(d.get("findings", []))

    print(f"  │")
    print(f"  └─")
    print()



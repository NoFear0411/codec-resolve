"""
VP8 codec string decoder.

VP8 uses a bare "vp8" tag with no profile/level parameters.
All VP8 decoders support the full spec: 8-bit 4:2:0 only.

Source: RFC 6386 (VP8 Data Format and Decoding Guide),
        WebM Container Guidelines.
"""


def decode_vp8(codec_string: str) -> dict:
    """
    Decode a VP8 codec string.

    Accepts only the bare string "vp8". Any dot-separated fields
    or unrecognized tags produce an error — VP8 has no parameters.
    """
    findings = []
    result = {
        "family": "vp8",
        "findings": findings,
    }

    s = codec_string.strip()
    result["codec_string_full"] = s

    # VP8 must be exactly "vp8" — no dot-separated fields
    if "." in s:
        parts = s.split(".")
        result["codec_string"] = s
        result["entry"] = parts[0].lower()
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "VP8_UNEXPECTED_FIELDS",
            "message": f"VP8 has no parameters — expected bare 'vp8', "
                       f"got {len(parts)} dot-separated fields",
        })
        return result

    if s.lower() != "vp8":
        result["codec_string"] = s
        result["verdict"] = "INVALID"
        findings.append({
            "severity": "error",
            "code": "VP8_ENTRY_UNKNOWN",
            "message": f"Expected 'vp8', got '{s}'",
        })
        return result

    result["entry"] = "vp8"
    result["codec_string"] = s
    result["codec_name"] = "VP8"
    result["bit_depth"] = 8
    result["chroma"] = "4:2:0"
    result["verdict"] = "valid"

    return result

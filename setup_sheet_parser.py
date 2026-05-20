"""
Deterministic parsing of Mastercam-style setup sheet PDFs (PyMuPDF text extraction).
Uses regex and label-based extraction; tolerates messy PDF text order.

Important: for many Mastercam setup sheet PDFs, PyMuPDF ``get_text`` does not preserve
the same line order as the printed layout. Tool blocks are therefore anchored on the
repeated ``#N - ...`` summary line and MFG / HOLDER / length fields are disambiguated
with patterns (see ``_resolve_mfg_holder_and_lengths``).
"""
import re
from typing import Any, Dict, List

import fitz  # PyMuPDF


def extract_pdf_text(file) -> Dict[str, Any]:
    """
    Extract raw text from a PDF using PyMuPDF, page by page.

    ``file`` may be:
    - ``bytes`` (PDF content)
    - a Streamlit ``UploadedFile`` (has ``getvalue()``)
    - any file-like object with ``read()`` returning bytes

    Returns:
        ``full_text``: concatenation of all page texts (pages joined with newlines)
        ``pages``: list of ``{"page_number": int, "text": str}`` (1-based page_number)
    """
    if isinstance(file, bytes):
        pdf_bytes = file
    elif hasattr(file, "getvalue"):
        pdf_bytes = file.getvalue()
    elif hasattr(file, "read"):
        pdf_bytes = file.read()
    else:
        raise TypeError("file must be bytes, or support getvalue() or read()")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages: List[Dict[str, Any]] = []
        full_parts: List[str] = []
        for i in range(len(doc)):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            pages.append({"page_number": i + 1, "text": text})
            full_parts.append(text)
        full_text = "\n".join(full_parts)
        return {"full_text": full_text, "pages": pages}
    finally:
        doc.close()


def _norm_ws(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_metadata(text: str) -> Dict[str, Any]:
    t = _norm_ws(text)

    meta_patterns = [
        (r"(?:Project\s*Name|PROJECT\s*NAME)\s*[:\-]\s*([^\n]+)", "project_name"),
        (r"(?:Customer|CUSTOMER)\s*(?:Name)?\s*[:\-]\s*([^\n]+)", "customer_name"),
        (r"(?:Programmer|PROGRAMMER)\s*[:\-]\s*([^\n]+)", "programmer"),
        (r"(?:Drawing|DRAWING)\s*(?:No\.?|Number)?\s*[:\-]\s*([^\n]+)", "drawing"),
        (r"(?:Revision|REV\.?|REV)\s*[:\-]\s*([^\n]+)", "revision"),
        (r"(?:Date|DATE)\s*[:\-]\s*([^\n]+)", "date"),
        (r"(?:POST\s*LIC|Post)\s*[:\-]\s*([^\n]+)", "post"),
    ]

    out = {
        "project_name": "-",
        "customer_name": "-",
        "programmer": "-",
        "drawing": "-",
        "revision": "-",
        "date": "-",
        "post": "-",
        "comments": "-",
        "total_cycle_time": "-",
        "operation_list": [],
    }

    for pat, key in meta_patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m and out.get(key) == "-":
            val = m.group(1).strip()
            val = re.sub(r"\s+", " ", val)
            if val:
                out[key] = val

    # Comments: longer block after Comments / NOTES / COMMENT
    cm = re.search(
        r"(?:Comments?|NOTES|COMMENT)\s*[:\-]\s*([\s\S]{10,800}?)(?=\n\s*(?:Project|Customer|Drawing|Tool|Operation|Cycle|T\s*\d|\Z))",
        t,
        re.IGNORECASE,
    )
    if cm:
        c = cm.group(1).strip()
        c = re.sub(r"\s+", " ", c)
        if len(c) > 2:
            out["comments"] = c[:2000] if len(c) > 2000 else c

    # Total cycle time (various labels)
    ct = re.search(
        r"(?:Total\s*)?(?:Cycle\s*Time|CYCLE\s*TIME|RUN\s*TIME)\s*[:\-]\s*([^\n]+)",
        t,
        re.IGNORECASE,
    )
    if ct:
        out["total_cycle_time"] = ct.group(1).strip()

    # Operation list: numbered lines or Op / Operation rows
    ops: List[str] = []
    for line in t.split("\n"):
        line = line.strip()
        if not line:
            continue
        om = re.match(
            r"^\s*(?:Op\.?|Operation|OP)\s*[:\-]?\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if om:
            ops.append(om.group(1).strip())
            continue
        nm = re.match(r"^\s*\d+\.\s+(.{4,120})$", line)
        if nm and len(ops) < 50:
            candidate = nm.group(1).strip()
            if not re.match(r"^(T\s*\d+|G\d+|M\d+)", candidate, re.I):
                ops.append(candidate)
    out["operation_list"] = ops[:40]

    return out


# Tool row: starts with T and digits (Mastercam tool #)
_TOOL_START_RE = re.compile(r"^\s*T\s*(\d+)\b\s*(.*)$", re.IGNORECASE)

# Mastercam setup sheet: tool summary line (visual order is usually last in each tool block).
# PyMuPDF often emits label lines (HOLDER:, MFG CODE:, etc.) with the *following* lines
# swapped vs what you see on screen — e.g. after HOLDER: you get the MFG part number and
# the overall length, and after MFG CODE: you get the holder code and flute length.
_TOOL_ANCHOR_RE = re.compile(r"^\s*#\s*(\d+)\s*-\s*(.+)$", re.MULTILINE | re.IGNORECASE)

# Part-number style MFG codes like "00037697 / 1431" or "74127135 / 1527"
_MFG_CODE_RE = re.compile(r"\b(\d{4,}\s*/\s*\d+)\b")

# Holder codes like "C4C4-0016" (alphanumeric + hyphen + suffix)
_HOLDER_CODE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,7}-\d{3,}[A-Za-z0-9-]*)\b")


def _empty_tool_row(tool_number: str) -> Dict[str, Any]:
    return {
        "tool_number": tool_number,
        "tool_description": "-",
        "tool_type": "-",
        "length_offset": "-",
        "diameter_offset": "-",
        "holder": "-",
        "mfg_code": "-",
        "overall_length": "-",
        "flute_length": "-",
        "tip_angle": "-",
        "diameter": "-",
        "corner_radius": "-",
        "number_of_flutes": "-",
    }


def _guess_tool_type(desc: str) -> str:
    d = desc.upper()
    if not desc or desc == "-":
        return "-"
    if "DRILL" in d or "PECK" in d:
        return "DRILL"
    if "REAM" in d:
        return "REAM"
    if "CHAMFER" in d or "CHAM" in d:
        return "CHAMFER"
    if "SPOT" in d:
        return "SPOT DRILL"
    if "END MILL" in d or "ENDMILL" in d or "BALL" in d or "BULL" in d:
        return "END MILL"
    if "FACE" in d:
        return "FACE MILL"
    if "TAP" in d or "THREAD" in d:
        return "TAP"
    return "-"


def _parse_tool_tail(tail: str, full_line: str) -> Dict[str, Any]:
    """Parse remainder of a tool line and optional merged continuation."""
    combined = (tail + " " + full_line).strip()
    row = _empty_tool_row("T0")

    # Pipe-separated (similar to G-code header): T1 | desc | H1 | D31 | D0.25" | ...
    if "|" in tail:
        parts = [p.strip() for p in tail.split("|")]
        desc_idx = 0
        if parts and re.match(r"^T\s*\d+", parts[0], re.I):
            desc_idx = 1
        if desc_idx < len(parts) and parts[desc_idx]:
            row["tool_description"] = parts[desc_idx]
        for p in parts[desc_idx + 1 :]:
            pu = p.upper().strip()
            if re.match(r"^H\s*\d+$", pu.replace(" ", ""), re.I):
                row["length_offset"] = "H" + re.search(r"(\d+)", pu).group(1)
            elif re.match(r"^D\s*\d+$", pu.replace(" ", "")) and "." not in pu:
                row["diameter_offset"] = "D" + re.search(r"(\d+)", pu).group(1)
            elif '"' in p or re.search(r"D\s*\d+\.\d", p, re.I):
                row["diameter"] = p.strip()
            elif pu.startswith("R") and re.search(r"\d", pu):
                row["corner_radius"] = p.strip()
            elif pu and len(p) < 80 and row["tool_type"] == "-":
                row["tool_type"] = p

    # Length / dia offset H12 / D31 style (numbers only after labels on same blob)
    hm = re.search(r"\bH\s*(\d+)\b", combined, re.I)
    if hm and row["length_offset"] == "-":
        row["length_offset"] = "H" + hm.group(1)
    dm = re.search(r"\bD\s*(\d+)\b(?!\.)", combined)
    if dm and row["diameter_offset"] == "-":
        row["diameter_offset"] = "D" + dm.group(1)

    # Diameter as D0.2500"
    ddim = re.search(r"D\s*(\d+\.\d+)\s*\"?", combined, re.I)
    if ddim:
        row["diameter"] = "D" + ddim.group(1) + '"'

    cr = re.search(r"R\s*(\d+\.\d+)\s*\"?", combined, re.I)
    if cr and "corner" not in combined.lower():
        row["corner_radius"] = "R" + cr.group(1)

    # Overall / flute length labels nearby
    ol = re.search(
        r"(?:Overall\s*Length|OAL|LENGTH)\s*[:\-]?\s*(\d+\.\d+)",
        combined,
        re.I,
    )
    if ol:
        row["overall_length"] = ol.group(1)
    fl = re.search(
        r"(?:Flute\s*Length|FL)\s*[:\-]?\s*(\d+\.\d+)",
        combined,
        re.I,
    )
    if fl:
        row["flute_length"] = fl.group(1)

    tip = re.search(r"(?:Tip|TIP)\s*(?:Angle)?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*°?", combined, re.I)
    if tip:
        row["tip_angle"] = tip.group(1) + "°"

    nfl = re.search(r"(?:Flutes?|FLT)\s*[:\-]?\s*(\d+)\b", combined, re.I)
    if nfl:
        row["number_of_flutes"] = nfl.group(1)

    # MFG / holder codes (short alnum tokens)
    mfg = re.search(r"(?:MFG|Manufacturer|Vendor)\s*[:\-]?\s*([A-Z0-9\-]{3,20})", combined, re.I)
    if mfg:
        row["mfg_code"] = mfg.group(1)

    hol = re.search(r"(?:Holder|HLD)\s*[:\-]?\s*([^\n\|]{3,40})", combined, re.I)
    if hol:
        row["holder"] = hol.group(1).strip()

    return row


def _merge_tool_fields(base: Dict[str, Any], extra: Dict[str, Any]) -> None:
    for k, v in extra.items():
        if k == "tool_number":
            continue
        if v not in (None, "-", "") and base.get(k) in ("-", "", None):
            base[k] = v


def _label_line_value(block: str, label: str):
    """
    Value for ``Label:`` on the same line, or on the next non-empty line.
    Labels are matched case-insensitively at start of line.
    """
    esc = re.escape(label)
    m = re.search(rf"(?mi)^{esc}\s*:\s*(\S[^\n]*)\s*$", block)
    if m:
        v = m.group(1).strip()
        if v:
            return v
    m2 = re.search(rf"(?mi)^{esc}\s*:\s*\n\s*(\S[^\n]*)", block)
    if m2:
        v = m2.group(1).strip()
        if v:
            return v
    return None


def _decimals_in_string(s: str) -> List[float]:
    out = []
    for mm in re.finditer(r"\d+\.\d+", s):
        out.append(float(mm.group()))
    return out


def _standalone_decimal_lines(block: str) -> List[float]:
    """Lines that are only a decimal number (common for OAL / flute when labels are wrong)."""
    vals = []
    for line in block.splitlines():
        s = line.strip()
        if re.match(r"^-?\d+\.\d+$", s):
            vals.append(float(s))
    return vals


def _fmt_trim_float(v: float) -> str:
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return s if s else "0"


def _resolve_mfg_holder_and_lengths(block: str, row: Dict[str, Any]) -> None:
    """
    Fix MFG / HOLDER / overall_length / flute_length when PyMuPDF order does not match
    the printed Mastercam layout.

    Observed bad extraction pattern (labels do not match the following lines)::

        HOLDER:
        00037697 / 1431
        0.625
        MFG CODE:
        C4C4-0016
        0.5
        OVERALL LENGTH:
        FLUTE LENGTH:

    Visual meaning::

        mfg_code = 00037697 / 1431
        overall_length = 0.625
        holder = C4C4-0016
        flute_length = 0.5

    We never assign the MFG-style string to holder or vice versa.
    """
    # Prefer same-line / next-line label parsing when values look correct
    mfg_labeled = _label_line_value(block, "MFG CODE")
    if mfg_labeled and _MFG_CODE_RE.search(mfg_labeled):
        row["mfg_code"] = _MFG_CODE_RE.search(mfg_labeled).group(1).strip()

    holder_labeled = _label_line_value(block, "HOLDER")
    if holder_labeled and _HOLDER_CODE_RE.search(holder_labeled):
        row["holder"] = _HOLDER_CODE_RE.search(holder_labeled).group(1).strip()

    ovl_labeled = _label_line_value(block, "OVERALL LENGTH")
    if ovl_labeled and re.match(r"^\d+\.\d+$", ovl_labeled.strip()):
        row["overall_length"] = ovl_labeled.strip()

    fl_labeled = _label_line_value(block, "FLUTE LENGTH")
    if fl_labeled and re.match(r"^\d+\.\d+$", fl_labeled.strip()):
        row["flute_length"] = fl_labeled.strip()

    # MFG from anywhere in block (part number pattern)
    if row["mfg_code"] == "-":
        mm = _MFG_CODE_RE.search(block)
        if mm:
            row["mfg_code"] = mm.group(1).strip()

    # Holder: first token matching holder-code shape, not inside mfg_code string
    if row["holder"] == "-":
        for hm in _HOLDER_CODE_RE.finditer(block):
            span = hm.group(1)
            if row["mfg_code"] != "-" and span in row["mfg_code"]:
                continue
            row["holder"] = span.strip()
            break

    # Length pair: prefer two standalone decimals not used as diameter / anchor decoration
    exclude = set()
    anchor_line = ""
    for line in block.splitlines():
        stripped = line.strip()
        if _TOOL_ANCHOR_RE.match(stripped):
            anchor_line = stripped
            break
    for v in _decimals_in_string(anchor_line):
        exclude.add(round(v, 6))

    dia_val = _label_line_value(block, "DIAMETER")
    if dia_val:
        try:
            exclude.add(round(float(dia_val.strip()), 6))
        except ValueError:
            pass

    standalone = _standalone_decimal_lines(block)
    standalone = [v for v in standalone if round(v, 6) not in exclude]

    if row["overall_length"] == "-" or row["flute_length"] == "-":
        if len(standalone) >= 2:
            mx = max(standalone)
            mn = min(standalone)
            if row["overall_length"] == "-" and row["flute_length"] == "-":
                row["overall_length"] = _fmt_trim_float(mx)
                row["flute_length"] = _fmt_trim_float(mn)
            elif row["overall_length"] == "-":
                row["overall_length"] = _fmt_trim_float(mx)
            elif row["flute_length"] == "-":
                row["flute_length"] = _fmt_trim_float(mn)
        elif len(standalone) == 1:
            v = standalone[0]
            if row["overall_length"] == "-":
                row["overall_length"] = _fmt_trim_float(v)
            elif row["flute_length"] == "-":
                row["flute_length"] = _fmt_trim_float(v)


def _parse_mastercam_pdf_tool_block(block: str):
    """
    Parse one tool section anchored at ``#N - description`` (Mastercam setup sheet).

    Field lines may appear above that anchor in extraction order; the block slice
    includes all lines from the previous anchor through this anchor line.
    """
    m = _TOOL_ANCHOR_RE.search(block)
    if not m:
        return None

    num = int(m.group(1))
    row = _empty_tool_row("T%d" % num)
    row["tool_number"] = "T%d" % num
    row["tool_description"] = m.group(2).strip()[:500]

    tv = _label_line_value(block, "TYPE")
    if tv:
        row["tool_type"] = tv.strip()
    if row["tool_type"] == "-":
        row["tool_type"] = _guess_tool_type(row["tool_description"])

    lo = _label_line_value(block, "LENGTH OFFSET")
    if lo and re.match(r"^\d+$", lo.strip()):
        row["length_offset"] = "H" + lo.strip()

    do = _label_line_value(block, "DIAMETER OFFSET")
    if do and re.match(r"^\d+$", do.strip()):
        row["diameter_offset"] = "D" + do.strip()

    dv = _label_line_value(block, "DIAMETER")
    if dv:
        row["diameter"] = dv.strip()

    cr = _label_line_value(block, "CORNER RADIUS")
    if cr:
        row["corner_radius"] = cr.strip()

    tip = _label_line_value(block, "TIP ANGLE")
    if tip:
        row["tip_angle"] = tip.strip()

    nfl = _label_line_value(block, "# OF FLUTES")
    if nfl and re.search(r"\d+", nfl):
        row["number_of_flutes"] = re.search(r"(\d+)", nfl).group(1)

    _resolve_mfg_holder_and_lengths(block, row)
    return row


def _parse_tool_list_mastercam_blocks(text: str) -> List[Dict[str, Any]]:
    """
    Split full PDF text on ``#N - ...`` tool summary lines and parse each slice.

    This path targets Mastercam setup sheets where each tool ends with a line like::

        #1 - 0.2500 FLAT ENDMILL - 1/4 FLAT ENDMILL

    Earlier lines may list TYPE / offsets / lengths with PyMuPDF order scrambled.
    """
    t = _norm_ws(text)
    matches = list(_TOOL_ANCHOR_RE.finditer(t))
    if not matches:
        return []

    tools: List[Dict[str, Any]] = []
    prev = 0
    for m in matches:
        chunk = t[prev : m.end()]
        prev = m.end()
        parsed = _parse_mastercam_pdf_tool_block(chunk)
        if parsed:
            tools.append(parsed)

    return sorted(tools, key=lambda r: int(re.sub(r"\D", "", r["tool_number"]) or "0"))


def parse_tool_list(text: str) -> List[Dict[str, Any]]:
    """
    Extract tool rows from full PDF text.

    Prefer Mastercam setup-sheet blocks delimited by ``#N - ...`` summary lines.
    PyMuPDF often emits HOLDER / MFG CODE / length lines in an order that does not
    match the printed sheet; see ``_resolve_mfg_holder_and_lengths`` for corrections.
    """
    mc_tools = _parse_tool_list_mastercam_blocks(text)
    if mc_tools:
        return mc_tools

    t = _norm_ws(text)
    lines = t.split("\n")
    tools: List[Dict[str, Any]] = []
    seen = set()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = _TOOL_START_RE.match(line)
        if m:
            num = int(m.group(1))
            tkey = "T%d" % num
            if tkey in seen:
                i += 1
                continue
            seen.add(tkey)
            tail = m.group(2).strip()
            # Merge next line if short continuation without new T
            continuation = ""
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt and not _TOOL_START_RE.match(nxt) and len(nxt) < 200:
                    if not re.match(r"^(Project|Customer|Drawing|Operation)\b", nxt, re.I):
                        continuation = " " + nxt
                        i += 1

            row = _empty_tool_row(tkey)
            parsed = _parse_tool_tail(tail + continuation, line)
            _merge_tool_fields(row, parsed)
            row["tool_number"] = tkey

            # Description: first sentence chunk of tail if not filled
            if row["tool_description"] in ("-", ""):
                desc = tail.split("|")[0].strip() if tail else "-"
                desc = re.sub(r"\s+", " ", desc)
                if len(desc) > 2:
                    row["tool_description"] = desc[:500]
            if row["tool_type"] == "-":
                row["tool_type"] = _guess_tool_type(row["tool_description"])

            tools.append(row)
        i += 1

    # Fallback: scan for "Tool # N" patterns
    if not tools:
        for m in re.finditer(r"(?:Tool\s*#?\s*|TOOL\s+)\s*(\d+)\s*[:\-]?\s*([^\n]{6,200})", t, re.I):
            num = int(m.group(1))
            tkey = "T%d" % num
            if tkey in seen:
                continue
            seen.add(tkey)
            row = _empty_tool_row(tkey)
            tail = m.group(2).strip()
            parsed = _parse_tool_tail(tail, "")
            _merge_tool_fields(row, parsed)
            row["tool_description"] = tail[:500] if tail else "-"
            row["tool_type"] = _guess_tool_type(row["tool_description"])
            tools.append(row)

    return sorted(tools, key=lambda r: int(re.sub(r"\D", "", r["tool_number"]) or "0"))


def parse_setup_sheet_text(text: str) -> Dict[str, Any]:
    """Parse extracted PDF text into structured setup sheet data."""
    meta = _extract_metadata(text)
    tools = parse_tool_list(text)
    return {
        "project_name": meta["project_name"],
        "customer_name": meta["customer_name"],
        "programmer": meta["programmer"],
        "drawing": meta["drawing"],
        "revision": meta["revision"],
        "date": meta["date"],
        "post": meta.get("post", "-"),
        "comments": meta["comments"],
        "total_cycle_time": meta["total_cycle_time"],
        "operation_list": meta["operation_list"],
        "tools": tools,
        "raw_text_preview": text[:4000] if text else "",
    }


def parse_setup_sheet_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    """Full pipeline: PDF bytes -> structured dict (includes raw extraction for debug)."""
    extracted = extract_pdf_text(pdf_bytes)
    text = extracted["full_text"]
    parsed = parse_setup_sheet_text(text)
    parsed["full_text"] = extracted["full_text"]
    parsed["pages"] = extracted["pages"]
    return parsed


def _tool_sort_key(tool_str: str) -> int:
    m = re.search(r"(\d+)", tool_str or "")
    return int(m.group(1)) if m else 9999


def _parse_h_d_from_gcode_cell(cell: str) -> str:
    """Take first H## or D## from formatted cell like 'H9, H10'."""
    if not cell or cell == "-":
        return "-"
    hm = re.search(r"H\s*(\d+)", cell, re.I)
    if hm:
        return "H" + hm.group(1)
    return "-"


def _parse_d_from_gcode_cell(cell: str) -> str:
    if not cell or cell == "-":
        return "-"
    # Prefer bare offset register D##
    for m in re.finditer(r"D\s*(\d+)\b", cell):
        # skip if looks like diameter D0.25
        start = m.start()
        ctx = cell[max(0, start - 2) : start + 8]
        if re.search(r"D\s*\d+\.\d", ctx):
            continue
        return "D" + m.group(1)
    return "-"


def combine_gcode_and_setup_sheet(
    gcode_result: Dict[str, Any],
    setup_sheet: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    Match tools by T number between G-code tool_rows and setup sheet tools list.
    Returns rows for the combined comparison table.
    """
    setup_tools = setup_sheet.get("tools") or []
    by_t = {}
    for st in setup_tools:
        tn = st.get("tool_number") or ""
        m = re.search(r"T\s*(\d+)", tn, re.I)
        if m:
            by_t["T%d" % int(m.group(1))] = st

    tool_rows = gcode_result.get("tool_rows") or []
    combined = []

    for gr in tool_rows:
        g_tool = gr.get("Tool") or ""
        gm = re.search(r"T\s*(\d+)", g_tool, re.I)
        if not gm:
            continue
        tkey = "T%d" % int(gm.group(1))
        st = by_t.get(tkey, {})

        g_h = _parse_h_d_from_gcode_cell(gr.get("H offsets", "-"))
        g_d = _parse_d_from_gcode_cell(gr.get("D offsets", "-"))

        ss_h = st.get("length_offset") or "-"
        ss_d = st.get("diameter_offset") or "-"
        if ss_h == "-":
            hm = re.search(r"H\s*(\d+)", str(st.get("tool_description", "")))
            if hm:
                ss_h = "H" + hm.group(1)

        combined.append(
            {
                "Tool": tkey,
                "G-code H Offset": g_h,
                "Setup Sheet H Offset": ss_h if ss_h != "-" else "-",
                "G-code D Offset": g_d,
                "Setup Sheet D Offset": ss_d if ss_d != "-" else "-",
                "Tool Type": st.get("tool_type") or "-",
                "Diameter": st.get("diameter") or "-",
                "Holder": st.get("holder") or "-",
                "MFG Code": st.get("mfg_code") or "-",
                "Overall Length": st.get("overall_length") or "-",
                "Flute Length": st.get("flute_length") or "-",
            }
        )

    # Setup sheet tools not present in G-code
    g_tools = set()
    for gr in tool_rows:
        m = re.search(r"T\s*(\d+)", gr.get("Tool") or "")
        if m:
            g_tools.add("T%d" % int(m.group(1)))

    for tkey, st in sorted(by_t.items(), key=lambda x: _tool_sort_key(x[0])):
        if tkey in g_tools:
            continue
        combined.append(
            {
                "Tool": tkey,
                "G-code H Offset": "-",
                "Setup Sheet H Offset": st.get("length_offset") or "-",
                "G-code D Offset": "-",
                "Setup Sheet D Offset": st.get("diameter_offset") or "-",
                "Tool Type": st.get("tool_type") or "-",
                "Diameter": st.get("diameter") or "-",
                "Holder": st.get("holder") or "-",
                "MFG Code": st.get("mfg_code") or "-",
                "Overall Length": st.get("overall_length") or "-",
                "Flute Length": st.get("flute_length") or "-",
            }
        )

    return combined

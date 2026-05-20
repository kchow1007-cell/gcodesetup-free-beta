import re


PROGRAM_RE = re.compile(r"O(\d+)", re.IGNORECASE)
UNITS_RE = re.compile(r"G(20|21)", re.IGNORECASE)
WCS_RE = re.compile(r"G(5[4-9])(?:P(\d+))?(?!P)", re.IGNORECASE)
TOOL_RE = re.compile(r"(?<![A-Z0-9#])T(\d+)", re.IGNORECASE)
G43_G44_RE = re.compile(r"G4[34]", re.IGNORECASE)
# Integer tool-length H only (H01→H1); rejects H0.03 / macro decimals on G43/G44 lines.
G43_G44_H_RE = re.compile(r"H0*([1-9]\d*)(?![0-9.])", re.IGNORECASE)
G41_G42_RE = re.compile(r"G4[12]", re.IGNORECASE)
G41_G42_D_RE = re.compile(r"D0*([1-9]\d*)(?![0-9.])", re.IGNORECASE)
D_RE = re.compile(r"D(\d+)", re.IGNORECASE)
NUM_RE = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
S_RE = re.compile(r"S" + NUM_RE, re.IGNORECASE)
F_RE = re.compile(r"F" + NUM_RE, re.IGNORECASE)
COOLANT_RE = re.compile(r"M(8|9)", re.IGNORECASE)
M6_RE = re.compile(r"M0?6", re.IGNORECASE)
# T6M6, T6 M6, or T6 on the line above M6
TOOL_CHANGE_SAME_LINE_RE = re.compile(
    r"(?<![A-Z0-9#])T(\d+)(?:\s*M0?6|M0?6)",
    re.IGNORECASE,
)
AXIS_RE = re.compile(r"([XYZ])" + NUM_RE, re.IGNORECASE)
BLOCK_START_RE = re.compile(r"^\s*(N\d+)\b", re.IGNORECASE)
CANNED_CYCLE_RE = re.compile(r"G(8\d)", re.IGNORECASE)
COMMENT_RE = re.compile(r"\(([^)]*)\)")
SIEMENS_TOOL_COMMENT_RE = re.compile(r"^T(\d+)\s*[-–—]\s*(.*)$", re.IGNORECASE)
STANDALONE_TOOL_RE = re.compile(r"^\s*T(\d+)\s*$", re.IGNORECASE)
SIEMENS_TOOL_PRELOAD_RE = re.compile(r"^\s*T\s*=\s*\(\s*\d+\s*\)\s*$", re.IGNORECASE)
HEADER_TOOL_RE = re.compile(r"^\s*T(\d+)\s*\|", re.IGNORECASE)
G100_RE = re.compile(r"\bG100\b", re.IGNORECASE)
G100_TOOL_RE = re.compile(r"G100\s+T(\d+)", re.IGNORECASE)
# N1–N99 used as sequence markers before real operation N blocks (N1001, N201, …).
_SMALL_SEQUENCE_N_MAX = 99


def _new_tool_stats(tool_name):
    return {
        "tool": tool_name,
        "h_offsets": set(),
        "d_offsets": set(),
        "spindle_speeds": set(),
        "feedrates": set(),
        "coolant_states": set(),
        "min_x": None,
        "max_x": None,
        "min_y": None,
        "max_y": None,
        "min_z": None,
        "max_z": None,
    }


def _update_axis(tool_stats, axis, value):
    axis = axis.upper()
    if axis == "X":
        tool_stats["min_x"] = value if tool_stats["min_x"] is None else min(tool_stats["min_x"], value)
        tool_stats["max_x"] = value if tool_stats["max_x"] is None else max(tool_stats["max_x"], value)
    elif axis == "Y":
        tool_stats["min_y"] = value if tool_stats["min_y"] is None else min(tool_stats["min_y"], value)
        tool_stats["max_y"] = value if tool_stats["max_y"] is None else max(tool_stats["max_y"], value)
    elif axis == "Z":
        tool_stats["min_z"] = value if tool_stats["min_z"] is None else min(tool_stats["min_z"], value)
        tool_stats["max_z"] = value if tool_stats["max_z"] is None else max(tool_stats["max_z"], value)


def _extract_semicolon_comment(raw_line):
    """Return text after ``;`` on this line, or None if there is no semicolon comment."""
    if ";" not in raw_line:
        return None
    return raw_line.split(";", 1)[1].strip()


def _extract_comments_from_line(raw_line):
    """Parenthesis and semicolon comments from one source line."""
    found = []
    for comment in COMMENT_RE.findall(raw_line):
        c = comment.strip()
        if c:
            found.append(c)
    semi = _extract_semicolon_comment(raw_line)
    if semi:
        found.append(semi)
    return found


def _clean_line(raw_line):
    line_no_comment = COMMENT_RE.sub(" ", raw_line)
    if ";" in line_no_comment:
        line_no_comment = line_no_comment.split(";", 1)[0]
    return line_no_comment.upper()


def _extract_tool_length_h_offsets(clean_line):
    """
    Tool-length H registers from G43/G44 only (not G65 macros or decimal H0.03).
    Returns normalized values such as H1, H3, H10.
    """
    if not clean_line or not G43_G44_RE.search(clean_line):
        return []
    found = []
    for match in G43_G44_H_RE.finditer(clean_line):
        found.append("H%d" % int(match.group(1)))
    return found


def _extract_cutter_comp_d_offsets(clean_line):
    """D registers from G41/G42 cutter compensation lines only."""
    if not clean_line or not G41_G42_RE.search(clean_line):
        return []
    found = []
    for match in G41_G42_D_RE.finditer(clean_line):
        found.append("D%d" % int(match.group(1)))
    return found


def _is_preload_tool_line(clean_line, tool_change_seen_in_block):
    """Standalone ``T#`` after a tool change in the same operation — preload, not active tool."""
    if not tool_change_seen_in_block:
        return False
    return bool(STANDALONE_TOOL_RE.match(clean_line.strip()))


def _n_block_numeric(n_label):
    match = re.match(r"^N(\d+)$", (n_label or "").strip().upper())
    return int(match.group(1)) if match else None


def _is_superseded_small_n_block(lines, idx, forward_limit=12):
    """
    Ignore ``N1``/``N2``/``N3`` when immediately followed by a larger operation ``N####`` with a comment.
    ``N1`` + ``N1001 (ROUGH WEDGE)`` → start at ``N1001`` only.
    """
    block_match = BLOCK_START_RE.match(lines[idx])
    if not block_match:
        return False
    small_val = _n_block_numeric(block_match.group(1))
    if small_val is None or small_val > _SMALL_SEQUENCE_N_MAX:
        return False
    end = min(len(lines), idx + forward_limit)
    for j in range(idx + 1, end):
        next_match = BLOCK_START_RE.match(lines[j])
        if not next_match:
            continue
        large_val = _n_block_numeric(next_match.group(1))
        if large_val is not None and large_val > small_val:
            if COMMENT_RE.search(lines[j]) or _extract_semicolon_comment(lines[j]):
                return True
            if _extract_operation_comment_from_n_line(lines[j], next_match.group(1).upper()):
                return True
        break
    return False


def _tool_number_from_g100_line(clean_line):
    """Tool number from ``G100 T10`` custom post tool-change lines."""
    if not G100_RE.search(clean_line):
        return None
    match = G100_TOOL_RE.search(clean_line)
    if match:
        return "T%d" % int(match.group(1))
    return None


def _is_g100_safety_preload(lines, idx, forward_limit=10):
    """
    ``G100 T26`` alone before ``G100 T10 G00 ...`` — safety/pre-tool, not the operation tool.
    """
    clean = _clean_line(lines[idx])
    first_tool = _tool_number_from_g100_line(clean)
    if not first_tool:
        return False
    if re.search(r"\bG0?0\b|\bG0?1\b|\bS\d", clean):
        return False
    end = min(len(lines), idx + forward_limit)
    for j in range(idx + 1, end):
        if BLOCK_START_RE.match(lines[j].strip()):
            break
        next_clean = _clean_line(lines[j])
        if not G100_RE.search(next_clean):
            continue
        second_tool = _tool_number_from_g100_line(next_clean)
        if second_tool:
            return True
    return False


def _is_g100_operation_tool_line(clean_line):
    """``G100 T#`` line that selects the active tool (has motion/spindle, not preload-only)."""
    if not _tool_number_from_g100_line(clean_line):
        return False
    return bool(re.search(r"\bG0?0\b|\bG0?1\b|\bS\d", clean_line))


def _format_float_set(values):
    if not values:
        return "-"
    return ", ".join(
        str(int(v)) if float(v).is_integer() else ("%.4f" % v).rstrip("0").rstrip(".")
        for v in sorted(values)
    )


def _format_str_set(values):
    if not values:
        return "-"
    return ", ".join(sorted(values))


def _format_opt_float(value):
    if value is None:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return ("%.4f" % value).rstrip("0").rstrip(".")


def _tool_has_data(stats):
    return bool(
        stats["h_offsets"]
        or stats["d_offsets"]
        or stats["spindle_speeds"]
        or stats["feedrates"]
        or stats["coolant_states"]
        or stats["min_x"] is not None
        or stats["max_x"] is not None
        or stats["min_y"] is not None
        or stats["max_y"] is not None
        or stats["min_z"] is not None
        or stats["max_z"] is not None
    )


def _empty_range_stats():
    return {
        "min_x": None,
        "max_x": None,
        "min_y": None,
        "max_y": None,
        "min_z": None,
        "max_z": None,
    }


def _new_block_stats(block_number, block_line):
    return {
        "block_number": block_number,
        "block_line": block_line,
        "tool_number": None,
        "tool_comment": None,
        "operation_comment": None,
        "tool_description": None,
        "diameter_from_comment": None,
        "corner_radius_from_comment": None,
        "tool_description_from_header": "-",
        "h_offset_from_header": "-",
        "d_offset_from_header": "-",
        "h_offsets": set(),
        "d_offsets": set(),
        "spindle_speeds": set(),
        "feedrates": set(),
        "work_offsets": set(),
        "coolant_states": set(),
        "canned_cycles": set(),
        "min_x": None,
        "max_x": None,
        "min_y": None,
        "max_y": None,
        "min_z": None,
        "max_z": None,
    }


def _is_siemens_tool_preload_line(clean_line):
    """Ignore Siemens preload lines such as ``T=(6)`` — not the active tool."""
    return bool(SIEMENS_TOOL_PRELOAD_RE.match(clean_line.strip()))


def _tool_number_from_clean_line(clean_line):
    """First real T# on a cleaned line (not ``T=(6)`` preload)."""
    line = clean_line.strip()
    if _is_siemens_tool_preload_line(line):
        return None
    standalone = STANDALONE_TOOL_RE.match(line)
    if standalone:
        return "T%d" % int(standalone.group(1))
    combined = _tool_number_from_tool_change_line(clean_line)
    if combined:
        return combined
    match = TOOL_RE.search(clean_line)
    if match:
        return "T%d" % int(match.group(1))
    return None


def _tool_number_from_tool_change_line(clean_line):
    """T# from combined tool-change lines: T6M6, T6 M6."""
    match = TOOL_CHANGE_SAME_LINE_RE.search(clean_line)
    if match:
        return "T%d" % int(match.group(1))
    return None


def _resolve_tool_at_m6(lines, m6_line_idx, lookback=12):
    """
    Active tool for M6: same line (``T6M6``, ``T6 M6``) or T# shortly above (``T6`` then ``M6``).
    """
    clean_m6 = _clean_line(lines[m6_line_idx])
    same_line = _tool_number_from_tool_change_line(clean_m6) or _tool_number_from_clean_line(
        clean_m6
    )
    if same_line:
        return same_line

    j = m6_line_idx - 1
    steps = 0
    while j >= 0 and steps < lookback:
        prev_strip = lines[j].strip()
        if not prev_strip:
            j -= 1
            steps += 1
            continue

        prev_clean = _clean_line(lines[j])
        if M6_RE.search(prev_clean):
            break

        if _is_siemens_tool_preload_line(prev_clean):
            j -= 1
            steps += 1
            continue

        tool = _tool_number_from_clean_line(prev_clean)
        if tool:
            return tool

        if prev_strip.startswith(";") or (prev_strip.startswith("(") and ")" in prev_strip):
            j -= 1
            steps += 1
            continue

        if BLOCK_START_RE.match(lines[j]):
            break

        j -= 1
        steps += 1

    return None


def _register_tool(tool_name, tools, tool_order):
    if tool_name not in tools:
        tools[tool_name] = _new_tool_stats(tool_name)
        tool_order.append(tool_name)


def _collect_work_offsets(line):
    offsets = set()
    for g_code, p_value in WCS_RE.findall(line):
        work_offset = "G" + g_code
        if p_value:
            work_offset += "P" + p_value
        offsets.add(work_offset)
    return offsets


def _format_comment(value):
    if not value:
        return "-"
    return value.strip() or "-"


def _extract_program_name_from_o_line(raw_line):
    program_match = PROGRAM_RE.search(raw_line)
    if not program_match:
        return None, None
    program_number = "O" + program_match.group(1)
    o_comment_match = COMMENT_RE.search(raw_line)
    program_name = o_comment_match.group(1).strip() if o_comment_match else None
    return program_number, program_name


def _build_program_header():
    return {
        "program_number": "-",
        "program_name": "-",
        "mastercam_version": "-",
        "mcx_file": "-",
        "material": "-",
        "nc_program_name": "-",
        "date": "-",
        "time": "-",
        "post": "-",
    }


def _parse_header_tool_comment(comment):
    if not HEADER_TOOL_RE.match(comment):
        return None
    parts = [p.strip() for p in comment.split("|")]
    if len(parts) < 2:
        return None
    tool_number_match = re.match(r"^T(\d+)", parts[0], re.IGNORECASE)
    if not tool_number_match:
        return None

    tool_number = "T%d" % int(tool_number_match.group(1))
    h_offset = "-"
    d_register = "-"
    tool_diameter = "-"
    corner_radius = "-"
    operation_type = "-"
    description = parts[1] if len(parts) >= 2 else ""

    for token in parts[2:]:
        token_up = token.upper()
        if token_up.startswith("H") and re.match(r"^H\d+$", token_up):
            h_offset = token_up
        elif token_up.startswith("D") and re.match(r"^D\d+$", token_up):
            d_register = token_up
        elif token_up.startswith("D") and len(token_up) > 1:
            tool_diameter = token
        elif token_up.startswith("R") and len(token_up) > 1:
            corner_radius = token
        elif token.strip():
            operation_type = token.strip()

    return {
        "tool_number": tool_number,
        "tool_description": description or "-",
        "h_offset": h_offset,
        "d_offset_register": d_register,
        "tool_diameter": tool_diameter,
        "corner_radius": corner_radius,
        "operation_type": operation_type,
        "raw_comment": comment.strip(),
    }


def _parse_program_header_and_tool_table(lines):
    program_header = _build_program_header()
    header_tool_table = []
    seen_tools = set()
    first_operation_index = None

    for idx, raw_line in enumerate(lines):
        if BLOCK_START_RE.match(raw_line) and _n_block_has_operation_signals(lines, idx):
            first_operation_index = idx
            break

    scan_limit = first_operation_index if first_operation_index is not None else len(lines)

    for raw_line in lines[:scan_limit]:
        raw_number, raw_name = _extract_program_name_from_o_line(raw_line)
        if raw_number and program_header["program_number"] == "-":
            program_header["program_number"] = raw_number
        if raw_name and program_header["program_name"] == "-":
            program_header["program_name"] = raw_name

        for comment in _extract_comments_from_line(raw_line):
            c = comment.strip()
            if not c:
                continue
            c_up = c.upper()
            parsed_tool = _parse_header_tool_comment(c)
            if not parsed_tool:
                parsed_tool = _parse_semicolon_tool_comment(c)
                if parsed_tool:
                    parsed_tool = {
                        "tool_number": parsed_tool["tool_number"],
                        "tool_description": parsed_tool["tool_description"],
                        "h_offset": "-",
                        "d_offset_register": parsed_tool.get("d_offset") or "-",
                        "tool_diameter": "-",
                        "corner_radius": "-",
                        "operation_type": "-",
                        "raw_comment": c,
                    }
            if parsed_tool:
                if parsed_tool["tool_number"] not in seen_tools:
                    header_tool_table.append(parsed_tool)
                    seen_tools.add(parsed_tool["tool_number"])
                continue

            if c_up.startswith("MASTERCAM") and program_header["mastercam_version"] == "-":
                val = c.split("-", 1)[1].strip() if "-" in c else c
                program_header["mastercam_version"] = val
            elif c_up.startswith("MCX FILE") and program_header["mcx_file"] == "-":
                val = c.split("-", 1)[1].strip() if "-" in c else c
                program_header["mcx_file"] = val
            elif c_up.startswith("MATERIAL") and program_header["material"] == "-":
                val = c.split("-", 1)[1].strip() if "-" in c else c
                program_header["material"] = val
            elif c_up.startswith("PROGRAM") and program_header["nc_program_name"] == "-":
                val = c.split("-", 1)[1].strip() if "-" in c else c
                program_header["nc_program_name"] = val
            elif c_up.startswith("DATE") and program_header["date"] == "-":
                val = c.split("-", 1)[1].strip() if "-" in c else c
                program_header["date"] = val
            elif c_up.startswith("TIME") and program_header["time"] == "-":
                val = c.split("-", 1)[1].strip() if "-" in c else c
                program_header["time"] = val
            elif c_up.startswith("POST LIC") and program_header["post"] == "-":
                val = c.split("-", 1)[1].strip() if "-" in c else c
                program_header["post"] = val

    return program_header, header_tool_table


def _parse_semicolon_tool_comment(comment):
    """
    Parse Siemens-style tool lines such as:
    ``T6 - 1/2 FLAT ENDMILL - D1 - DIA .5"``
    """
    if not comment:
        return None
    match = SIEMENS_TOOL_COMMENT_RE.match(comment.strip())
    if not match:
        return None

    tool_number = "T%d" % int(match.group(1))
    rest = match.group(2).strip().strip('"')
    d_offset = None
    d_match = re.search(r"\b(D\d+)\b", rest, re.IGNORECASE)
    if d_match:
        d_offset = d_match.group(1).upper()

    description = rest
    parts = re.split(r"\s*[-–—]\s*", rest)
    desc_parts = []
    for part in parts:
        token = part.strip().strip('"')
        if not token:
            continue
        if re.match(r"^D\d+$", token, re.IGNORECASE):
            break
        if token.upper().startswith("DIA"):
            continue
        if token.upper().startswith("CORNER"):
            continue
        desc_parts.append(token)
    if desc_parts:
        description = " ".join(desc_parts)

    diameter = None
    corner_radius = None
    dia_m = re.search(r"\bDIA\.?\s*([0-9.]+)", rest, re.IGNORECASE)
    if dia_m:
        diameter = dia_m.group(1)
    cr_m = re.search(r"CORNER\s*RAD\.?\s*([0-9.]+)", rest, re.IGNORECASE)
    if cr_m:
        corner_radius = cr_m.group(1)

    return {
        "tool_number": tool_number,
        "tool_description": description.strip() or "-",
        "d_offset": d_offset,
        "diameter": diameter,
        "corner_radius": corner_radius,
    }


_IGNORED_COMMENT_TERMS = (
    "TOOLPLANE",
    "MASTERCAM",
    "MCX FILE",
    "MATERIAL",
    "PROGRAM",
    "DATE",
    "TIME",
    "POST",
    "GOTO",
    "WHILE",
    "H-WEAR",
    "D-GEOM",
    "D-WEAR",
    "R-WEAR",
    "R-GEOM",
    "LENGTH AND WEAR",
    "M30",
)

# Makino / ProNC preamble lines — never operation or tool description.
_MAKINO_METADATA_COMMENT_RE = re.compile(
    r"^(?:DEPTH\b|BL\s*#|OPERATION\s+NO\b|OPERATION\s+TYPE\b|LENGTH\s+AND\s+WEAR\b)",
    re.IGNORECASE,
)

_CAM_PROCESS_COMMENT_PATTERNS = (
    r"^TOOLPATH\b",
    r"TOOLPATH\s*[-–—]",
    r"STOCK\s+LEFT",
    r"STOCK\s+LEFT\s+ON\s+DRIVE\s+SURFS",
    r"STOCK\s+LEFT\s+ON\s+CHECK\s+SURFS",
    r"THERMAL\s+DISPLACEMENT\s+COMPENSATION",
)

_TOOL_WORD_PATTERNS = (
    r"ENDMILL",
    r"DRILL",
    r"REAMER",
    r"\bBALL\b",
    r"\bBULL\b",
    r"CHAMFER",
    r"CORNER\s*ROUNDER",
    r"KEYCUTTER",
    r"SPOT\s*DRILL",
    r"TAPERED",
    r"SPHERICAL",
    r"FACE\s*MILL",
    r"\bE/M\b",
    r"\bEM\b",
    r"\bNOSED\b",
    r"COUNTERBORE",
    r"ROUGHING",
    r"BORING",
    r"TAP\b",
)

_TOOL_COMMENT_PATTERNS = (
    (r"TOOL\s*[-–—]", 4),
    (r"DIA\.?\s*OFF", 5),
    (r"\bLEN\.?", 4),
    (r"TOOL\s+DIA", 5),
    (r"ENDMILL", 3),
    (r"DRILL", 2),
    (r"REAMER", 3),
    (r"CHAMFER\s+MILL", 4),
    (r"\bCHAMFER\b", 2),
    (r"\bBALL\b", 2),
    (r"SPOT\s*DRILL", 4),
    (r"CORNER\s*ROUNDER", 4),
    (r"KEYCUTTER", 4),
    (r"FLAT\s*ENDMILL", 4),
    (r"BULL\s*ENDMILL", 4),
    (r"BULL[-\s]*NOSED", 5),
    (r"\bNOSED\b", 3),
    (r"\bTAPERED\b", 3),
    (r"\bSPHERICAL\b", 3),
    (r"FACE\s*MILL", 4),
    (r"\bE/M\b", 3),
    (r"^T\d+\s*[-–—]", 6),
    (r"\bT\d+\b", 2),
    (r"\bD\d+\b", 2),
    (r"\bDIA\b", 2),
    (r"D\s*=\s*\d+", 4),
    (r"H\s*=\s*\d+", 3),
    (r"DIAMETER\s*=", 4),
)

_OPERATION_COMMENT_PATTERNS = (
    (r"\bROUGH(?!ING)\b", 4),
    (r"\bFINISH\b", 4),
    (r"\bPROFILE\b", 4),
    (r"\bFACE\b", 3),
    (r"\bPOCKET\b", 4),
    (r"\bBORE\b", 3),
    (r"\bREAM(?!ER)\b", 3),
    (r"DRILL\s+HOLE", 5),
    (r"SPOT\s+HOLE", 5),
    (r"CHAMFER\s+TOP", 5),
    (r"CUT\s+OFF", 4),
    (r"\bSURFACE\b", 3),
    (r"\bCONTOUR\b", 4),
    (r"\bSLOT\b", 3),
    (r"\bEDGE\b", 2),
    (r"\bCENTER\b", 2),
    (r"\bOUTSIDE\b", 3),
    (r"\bINSIDE\b", 3),
    (r"\bRADIUS\b", 3),
    (r"\bTOP\b", 2),
    (r"\bBACK\b", 2),
    (r"\bLEFT\b", 2),
    (r"\bRIGHT\b", 2),
    (r"\bCUT\b", 2),
    (r"\bDYNAMIC\b", 4),
)


def _is_cam_process_comment(comment):
    if not comment:
        return True
    c_up = comment.strip().upper()
    for pattern in _CAM_PROCESS_COMMENT_PATTERNS:
        if re.search(pattern, c_up):
            return True
    return False


def _has_tool_word(text):
    """True when text names a cutter type (ENDMILL, DRILL, BULL, …)."""
    if not text:
        return False
    for pattern in _TOOL_WORD_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _is_valid_tool_description(description):
    """Reject CAM/process-only strings for ``tool_description``."""
    if not description:
        return False
    d = description.strip()
    if not d or d == "-":
        return False
    if _is_cam_process_comment(d):
        return False
    return _has_tool_word(d)


_TOOL_DESC_METADATA_CUT_PATTERNS = (
    r"\s+TOOL\s*[-–—]\s*\d",
    r"\s+TOOL\s*[-–—]",
    r"\s+DIA\.?\s*OFF\.?",
    r"\s+DIA\s+OFF",
    r"\s+DIA\.?\s*[-–—]",
    r"\s+DIA\s*[-–—]",
    r"\s+LEN\.?",
    r"\s+LENGTH\s+OFFSET",
    r"\s+TOOL\s+DIA\.?",
    r"\s+TOOL\s+DIAMETER",
    r"\s+DIAMETER\s*=",
    r"\s+D\s*=",
    r"\s+H\s*=",
    r"\s+[-–—]\s*D\d+\b",
    r"\s+[-–—]\s*DIA\b",
    r"\s+[-–—]\s*CORNER\s+RAD",
)


def clean_tool_description(text):
    """
    Strip offset/diameter metadata from a tool comment, leaving the cutter name only.
    Mastercam pipe-separated comments keep only the first ``|`` segment.
    """
    if text is None:
        return ""
    c = str(text).strip()
    if not c or c == "-":
        return ""

    if "|" in c:
        c = c.split("|", 1)[0].strip()

    earliest = len(c)
    for pattern in _TOOL_DESC_METADATA_CUT_PATTERNS:
        match = re.search(pattern, c, re.IGNORECASE)
        if match and match.start() < earliest:
            earliest = match.start()
    if earliest < len(c):
        c = c[:earliest]

    c = re.sub(r"\s+H\d+\s*$", "", c, flags=re.IGNORECASE).strip()
    c = re.sub(r"\s+", " ", c).strip()
    c = c.rstrip("-–—|,").strip()
    return c


def _trailing_h_offset_from_tool_text(text):
    """Trailing ``H2`` on tool comments (Makino M06 lines); not ``H=`` metadata."""
    if not text:
        return None
    match = re.search(r"(?<![A-Z0-9#.=])\s+H(\d+)\s*$", str(text).strip(), re.IGNORECASE)
    if match:
        return "H%d" % int(match.group(1))
    return None


def _sanitize_tool_description(description):
    cleaned = clean_tool_description(description)
    if _is_valid_tool_description(cleaned):
        return cleaned
    return None


def _is_makino_metadata_comment(comment):
    if not comment:
        return False
    return bool(_MAKINO_METADATA_COMMENT_RE.match(comment.strip()))


def _is_ignored_comment(comment):
    if not comment:
        return True
    c_up = comment.strip().upper()
    if HEADER_TOOL_RE.match(comment.strip()):
        return True
    if _is_cam_process_comment(comment):
        return True
    if _is_makino_metadata_comment(comment):
        return True
    for term in _IGNORED_COMMENT_TERMS:
        if term in c_up:
            return True
    return False


def _tool_comment_score(comment):
    if not comment or _is_ignored_comment(comment):
        return 0
    score = 0
    for pattern, weight in _TOOL_COMMENT_PATTERNS:
        if re.search(pattern, comment, re.IGNORECASE):
            score += weight
    if _parse_semicolon_tool_comment(comment):
        score += 12
    return score


def _operation_comment_score(comment):
    if not comment or _is_ignored_comment(comment):
        return 0
    score = 0
    for pattern, weight in _OPERATION_COMMENT_PATTERNS:
        if re.search(pattern, comment, re.IGNORECASE):
            score += weight
    return score


def _is_tool_comment(comment):
    if _is_cam_process_comment(comment):
        return False
    if _parse_semicolon_tool_comment(comment) or _parse_mastercam_inline_tool_comment(comment):
        return True
    tool_score = _tool_comment_score(comment)
    if tool_score <= 0:
        return False
    op_score = _operation_comment_score(comment)
    if _has_tool_word(comment):
        return tool_score > op_score
    return tool_score >= 3 and tool_score > op_score


def _is_operation_comment(comment):
    op_score = _operation_comment_score(comment)
    if op_score <= 0:
        return False
    return op_score >= _tool_comment_score(comment)


def _strip_block_number_from_comment(comment, block_number):
    """``( N101 DYNAMIC MILL )`` → ``DYNAMIC MILL`` when block is ``N101``."""
    if not comment:
        return ""
    cleaned = comment.strip()
    if not block_number or block_number == "-":
        return cleaned
    bn = block_number.strip().upper()
    if not bn:
        return cleaned
    if cleaned.upper().startswith(bn):
        cleaned = cleaned[len(bn) :].lstrip(" -:\t")
    return cleaned.strip()


def clean_operation_comment(comment, block_number=None):
    """
    Strip leading ``N####`` prefixes and repeated block numbers from operation text.
    """
    if comment is None:
        return ""
    text = str(comment).strip()
    if not text or text == "-":
        return ""

    parts = [p.strip() for p in re.split(r"[\r\n]+", text) if p.strip()]
    if len(parts) > 1:
        bn = (block_number or "").strip().upper()
        if bn and bn != "-":
            chosen = None
            for part in parts:
                if part.upper().startswith(bn):
                    chosen = part
                    break
            text = chosen if chosen else parts[-1]
        else:
            text = parts[-1]
    else:
        text = parts[0] if parts else text

    c = text
    while True:
        match = re.match(r"^N\d+\s*", c, re.IGNORECASE)
        if not match:
            break
        c = c[match.end() :].lstrip(" -:\t")

    if block_number and block_number != "-":
        c = _strip_block_number_from_comment(c, block_number)

    c = re.sub(r"\s+", " ", c).strip()
    return c


def _clean_operation_comment(operation_comment, block_number):
    """Internal alias for ``clean_operation_comment``."""
    cleaned = clean_operation_comment(operation_comment, block_number)
    return cleaned if cleaned else operation_comment


def _line_has_inline_tool_change(raw_line):
    """``N#### T# M6 (tool comment)`` — inline parens are tool description, not operation."""
    if not BLOCK_START_RE.match(raw_line):
        return False
    clean = _clean_line(raw_line)
    return bool(TOOL_RE.search(clean) and M6_RE.search(clean))


def _extract_operation_comment_from_n_line(raw_line, block_number):
    """Operation text from inline ``N#### ( N#### OPERATION )`` comment."""
    if not BLOCK_START_RE.match(raw_line):
        return None
    if _line_has_inline_tool_change(raw_line):
        return None
    for comment in _extract_comments_from_line(raw_line):
        if _is_ignored_comment(comment) or _is_cam_process_comment(comment):
            continue
        cleaned = _strip_block_number_from_comment(comment, block_number)
        if not cleaned:
            continue
        if _is_tool_comment(cleaned):
            continue
        return clean_operation_comment(cleaned, block_number)
    return None


def _parse_mastercam_inline_tool_comment(comment):
    """
    Mastercam/Fanuc tool line, e.g.
    ``( 3/8 FLAT ENDMILL D=1 H=1 DIAMETER=.375 )``
    """
    if not comment or _is_ignored_comment(comment):
        return None
    c = comment.strip()
    if not re.search(r"D\s*=\s*\d+|H\s*=\s*\d+|DIAMETER\s*=", c, re.IGNORECASE):
        return None
    if _tool_comment_score(c) < 2 and not re.search(
        r"ENDMILL|DRILL|REAM|BALL|MILL|CHAMFER|BOR", c, re.IGNORECASE
    ):
        return None

    d_offset = None
    h_offset = None
    diameter = None
    d_match = re.search(r"(?<![A-Z0-9#=])D\s*=\s*(\d+)", c, re.IGNORECASE)
    if d_match:
        d_offset = "D%d" % int(d_match.group(1))
    h_match = re.search(r"(?<![A-Z0-9#=])H\s*=\s*(\d+)", c, re.IGNORECASE)
    if h_match:
        h_offset = "H%d" % int(h_match.group(1))
    dia_match = re.search(r"DIAMETER\s*=\s*([0-9.]+)", c, re.IGNORECASE)
    if dia_match:
        diameter = dia_match.group(1)

    description = c
    for split_pat in (r"\s+D\s*=", r"\s+H\s*=", r"\s+DIAMETER\s*="):
        parts = re.split(split_pat, description, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) > 1:
            description = parts[0]
    description = description.strip() or "-"

    return {
        "tool_number": None,
        "tool_description": description,
        "h_offset": h_offset,
        "d_offset": d_offset,
        "diameter": diameter,
        "corner_radius": None,
    }


def _merge_tool_info_into_block(block_stats, info):
    """Apply parsed tool-comment fields; G43/G44 H on motion lines take priority later."""
    if not info:
        return
    if info.get("tool_number") and not block_stats["tool_number"]:
        block_stats["tool_number"] = info["tool_number"]
    desc = _sanitize_tool_description(info.get("tool_description"))
    if desc:
        block_stats["tool_description"] = desc
    if info.get("diameter"):
        block_stats["diameter_from_comment"] = info["diameter"]
    if info.get("corner_radius"):
        block_stats["corner_radius_from_comment"] = info["corner_radius"]
    if info.get("d_offset"):
        block_stats["d_offsets"].add(info["d_offset"])
    if info.get("h_offset") and not block_stats["h_offsets"]:
        block_stats["h_offsets"].add(info["h_offset"])


def _apply_tool_line_comments(block_stats, raw_line):
    """Inline ``( tool comment )`` on ``T# M06`` / ``T#M6`` / ``M06`` lines."""
    clean = _clean_line(raw_line)
    if not (_tool_number_from_tool_change_line(clean) or M6_RE.search(clean)):
        return
    for comment in _extract_comments_from_line(raw_line):
        if _is_ignored_comment(comment):
            continue
        info = _extract_tool_info_from_comment(comment)
        if not info and M6_RE.search(clean):
            h_trail = _trailing_h_offset_from_tool_text(comment)
            desc = clean_tool_description(comment)
            if desc:
                info = {
                    "tool_number": None,
                    "tool_description": desc,
                    "h_offset": h_trail,
                    "d_offset": None,
                    "diameter": None,
                    "corner_radius": None,
                }
        if info:
            block_stats["tool_comment"] = comment.strip()
            _merge_tool_info_into_block(block_stats, info)


def _clean_tool_description(comment):
    """Parse structured tool comments, then strip metadata tails for display."""
    if not comment:
        return "-"
    c = comment.strip()
    siemens = _parse_semicolon_tool_comment(c)
    if siemens:
        return clean_tool_description(siemens["tool_description"]) or "-"

    mastercam = _parse_mastercam_inline_tool_comment(c)
    if mastercam:
        return clean_tool_description(mastercam["tool_description"]) or "-"

    return clean_tool_description(c) or "-"


def _parse_fanuc_paren_tool_comment(comment):
    """
  Fanuc/Mastercam parenthesis tool lines, e.g.
  ``( 1/8 X 900 CHAMFER MILL TOOL - 14 DIA. OFF. - 14 LEN. - 14 TOOL DIA. - .125 )``
    """
    if not comment or _parse_semicolon_tool_comment(comment):
        return None
    c = comment.strip()
    if _tool_comment_score(c) < 3 and not re.search(r"TOOL\s*[-–—]", c, re.IGNORECASE):
        return None

    tool_number = None
    h_offset = None
    d_offset = None
    diameter = None

    t_match = re.search(r"\bT(\d+)\b", c, re.IGNORECASE)
    if t_match:
        n = int(t_match.group(1))
        tool_number = "T%d" % n
        h_offset = "H%d" % n
        d_offset = "D%d" % n

    dia_off_match = re.search(r"(\d+)\s+DIA\.?\s*OFF", c, re.IGNORECASE)
    if dia_off_match:
        n = int(dia_off_match.group(1))
        if not tool_number:
            tool_number = "T%d" % n
        if not h_offset:
            h_offset = "H%d" % n
        if not d_offset:
            d_offset = "D%d" % n

    tool_dia_match = re.search(r"TOOL\s+DIA\.?\s*[-–—]?\s*([0-9.]+)", c, re.IGNORECASE)
    if tool_dia_match:
        diameter = tool_dia_match.group(1)
    else:
        parts = re.split(r"\s*[-–—]\s*", c)
        if parts:
            last = parts[-1].strip().strip("()")
            if re.match(r"^\.?\d+$", last):
                diameter = last

    description = _clean_tool_description(c)
    if description == "-" and not tool_number:
        return None

    return {
        "tool_number": tool_number,
        "tool_description": description,
        "h_offset": h_offset,
        "d_offset": d_offset,
        "diameter": diameter,
        "corner_radius": None,
    }


def _extract_tool_info_from_comment(comment):
    """Unified tool metadata from Siemens ``;T#`` or Fanuc ``()`` tool comments."""
    if not comment or _is_ignored_comment(comment):
        return None

    siemens = _parse_semicolon_tool_comment(comment)
    if siemens:
        return {
            "tool_number": siemens["tool_number"],
            "tool_description": siemens["tool_description"],
            "h_offset": None,
            "d_offset": siemens.get("d_offset"),
            "diameter": siemens.get("diameter"),
            "corner_radius": siemens.get("corner_radius"),
        }

    mastercam = _parse_mastercam_inline_tool_comment(comment)
    if mastercam:
        return mastercam

    fanuc = _parse_fanuc_paren_tool_comment(comment)
    if fanuc:
        return fanuc

    if _is_tool_comment(comment):
        h_trail = _trailing_h_offset_from_tool_text(comment)
        desc = _sanitize_tool_description(_clean_tool_description(comment))
        if not desc:
            return None
        return {
            "tool_number": None,
            "tool_description": desc,
            "h_offset": h_trail,
            "d_offset": None,
            "diameter": None,
            "corner_radius": None,
        }
    return None


def _classify_block_comments(comments_ordered, block_number=None):
    """
    Return (best_tool_comment, best_operation_comment) using content scores, not order.
    """
    filtered = [c.strip() for c in comments_ordered if c and c.strip() and not _is_ignored_comment(c)]
    if not filtered:
        return None, None

    tool_ranked = []
    op_ranked = []
    for comment in filtered:
        if _is_cam_process_comment(comment):
            continue
        scored = _strip_block_number_from_comment(comment, block_number) or comment
        t_score = _tool_comment_score(scored)
        o_score = _operation_comment_score(scored)
        if t_score > 0 and t_score > o_score and _is_tool_comment(comment):
            tool_ranked.append((t_score, comment))
        elif o_score > 0 and o_score >= t_score:
            op_ranked.append((o_score, comment))
        elif t_score > 0:
            tool_ranked.append((t_score, comment))

    if len(filtered) == 1:
        only = filtered[0]
        scored_only = _strip_block_number_from_comment(only, block_number) or only
        t_score = _tool_comment_score(scored_only)
        o_score = _operation_comment_score(scored_only)
        if t_score > o_score:
            return only, None
        if o_score > t_score:
            return None, only
        if _is_tool_comment(only):
            return only, None
        if _is_operation_comment(only):
            return None, only
        return None, None

    best_tool = max(tool_ranked, key=lambda item: item[0])[1] if tool_ranked else None
    best_op = max(op_ranked, key=lambda item: item[0])[1] if op_ranked else None
    return best_tool, best_op


def _collect_pre_operation_comments(lines, start_idx, max_lookback=20):
    """
    Collect parenthesis and semicolon comments above an operation block.
    Skips blank lines and short T#/M6 preamble between comments and the block.
    """
    pre_comments = []
    j = start_idx - 1
    steps = 0
    while j >= 0 and steps < max_lookback:
        prev_strip = lines[j].strip()
        if not prev_strip:
            j -= 1
            steps += 1
            continue

        if prev_strip.startswith("(") and ")" in prev_strip:
            for comment in COMMENT_RE.findall(lines[j]):
                c = comment.strip()
                if c:
                    pre_comments.append(c)
            j -= 1
            steps += 1
            continue

        semi = _extract_semicolon_comment(lines[j])
        if semi or prev_strip.startswith(";"):
            if semi:
                pre_comments.append(semi)
            j -= 1
            steps += 1
            continue

        clean = _clean_line(lines[j])
        if TOOL_RE.search(clean) or M6_RE.search(clean):
            j -= 1
            steps += 1
            continue

        break

    return list(reversed(pre_comments))


def _apply_inline_tool_comments_to_block(block_stats, comments):
    """Paren comments on ``N#### T# M6`` lines are always tool description."""
    for comment in comments:
        if not comment or _is_ignored_comment(comment):
            continue
        block_stats["tool_comment"] = comment.strip()
        _merge_tool_info_into_block(block_stats, _extract_tool_info_from_comment(comment))


def _pick_operation_comment(comments_ordered, block_number=None):
    """
    First useful preamble comment (Makino: title line before ``N#### T#`` / ``M06``).
    """
    for comment in comments_ordered:
        if not comment or _is_ignored_comment(comment) or _is_makino_metadata_comment(comment):
            continue
        if _is_tool_comment(comment):
            continue
        cleaned = clean_operation_comment(comment, block_number)
        if cleaned:
            return cleaned
    return None


def _apply_preamble_comments_to_block(block_stats, comments_ordered):
    """
    Classify nearby preamble comments by content (tool vs operation), not comment order.
    Inline ``N#### T# M6`` comments are handled by ``_apply_inline_tool_comments_to_block``.
    """
    block_number = block_stats.get("block_number")
    best_tool, best_operation = _classify_block_comments(comments_ordered, block_number)

    if best_tool and not block_stats.get("tool_comment"):
        block_stats["tool_comment"] = best_tool
        _merge_tool_info_into_block(block_stats, _extract_tool_info_from_comment(best_tool))

    operation = _pick_operation_comment(comments_ordered, block_number)
    if not operation and best_operation:
        operation = clean_operation_comment(best_operation, block_number)
    if operation and not block_stats.get("operation_comment"):
        block_stats["operation_comment"] = operation


def _collect_following_preamble_comments(lines, start_idx, max_forward=32):
    """Paren/semicolon comments from N line through tool change (M6, G100 T#, or preload ``T#``)."""
    comments = []
    end = min(len(lines), start_idx + max_forward)
    for j in range(start_idx, end):
        if j > start_idx and BLOCK_START_RE.match(lines[j]):
            break
        strip = lines[j].strip()
        if not strip:
            continue
        clean = _clean_line(lines[j])

        semi = _extract_semicolon_comment(lines[j])
        if semi:
            comments.append(semi)
        for comment in COMMENT_RE.findall(lines[j]):
            c = comment.strip()
            if c:
                comments.append(c)

        if j == start_idx:
            continue
        if _is_siemens_tool_preload_line(clean):
            continue
        if _is_g100_safety_preload(lines, j):
            continue
        if STANDALONE_TOOL_RE.match(clean):
            break
        if _tool_number_from_tool_change_line(clean):
            break
        if M6_RE.search(clean) and not strip.startswith(";"):
            break
        if _is_g100_operation_tool_line(clean):
            break
    return comments


def _n_block_has_operation_signals(lines, n_idx, forward_limit=25):
    """
    After ``N####``, detect MPF/Fanuc operation signals before the next N block:
    semicolon/paren comments, standalone T#, or M6 with nearby T#.
    """
    end = min(len(lines), n_idx + forward_limit)
    saw_comment = False
    saw_tool_line = False
    saw_m6 = False

    for j in range(n_idx, end):
        if j > n_idx and BLOCK_START_RE.match(lines[j]):
            break
        strip = lines[j].strip()
        if not strip:
            continue
        clean = _clean_line(lines[j])

        if _extract_semicolon_comment(lines[j]):
            saw_comment = True
        for _c in COMMENT_RE.findall(lines[j]):
            if _c.strip():
                saw_comment = True

        if _is_siemens_tool_preload_line(clean):
            continue
        if STANDALONE_TOOL_RE.match(clean) or _tool_number_from_tool_change_line(clean):
            saw_tool_line = True
        if _tool_number_from_g100_line(clean) and not _is_g100_safety_preload(lines, j):
            saw_tool_line = True
        if M6_RE.search(clean):
            saw_m6 = True
        if TOOL_RE.search(clean) and M6_RE.search(clean):
            saw_tool_line = True
            saw_m6 = True

    if saw_tool_line and saw_m6:
        return True
    if saw_comment and (saw_tool_line or saw_m6):
        return True
    if saw_comment:
        for comment in _collect_following_preamble_comments(lines, n_idx, forward_limit):
            if _is_tool_comment(comment) or _is_operation_comment(comment):
                return True
    return False


def _standalone_tool_change_covered_by_n_block(lines, idx, lookback=30):
    """MPF: ``N####`` then comments then ``T#``/``M6`` — do not also start at standalone ``T#``."""
    for j in range(idx - 1, max(-1, idx - lookback) - 1, -1):
        if BLOCK_START_RE.match(lines[j]):
            return _n_block_has_operation_signals(lines, j)
    return False


def _is_operation_start(lines, idx):
    raw_line = lines[idx]
    clean_line = _clean_line(raw_line)

    if BLOCK_START_RE.match(raw_line):
        if _is_superseded_small_n_block(lines, idx):
            return False
        if TOOL_RE.search(clean_line) or M6_RE.search(clean_line):
            return True
        if _tool_number_from_g100_line(clean_line):
            return True
        if COMMENT_RE.search(raw_line) or _extract_semicolon_comment(raw_line):
            return True
        return _n_block_has_operation_signals(lines, idx)

    if _tool_number_from_clean_line(clean_line):
        if _standalone_tool_change_covered_by_n_block(lines, idx):
            return False
        end_idx = min(len(lines), idx + 12)
        for j in range(idx + 1, end_idx):
            if BLOCK_START_RE.match(lines[j]):
                break
            if M6_RE.search(_clean_line(lines[j])):
                return True
    return False


def _parse_operation_blocks(lines, header_tool_map):
    operation_blocks = []
    operation_start_indexes = []
    for idx in range(len(lines)):
        if _is_operation_start(lines, idx):
            operation_start_indexes.append(idx)
    if not operation_start_indexes:
        return operation_blocks

    for k, start_idx in enumerate(operation_start_indexes):
        end_idx = operation_start_indexes[k + 1] if k + 1 < len(operation_start_indexes) else len(lines)
        block_line_raw = lines[start_idx].strip()
        block_match = BLOCK_START_RE.match(lines[start_idx])
        block_number = block_match.group(1).upper() if block_match else "-"
        block_stats = _new_block_stats(block_number, block_line_raw)

        inline_tool_change_line = _line_has_inline_tool_change(lines[start_idx])
        start_line_comments = list(_extract_comments_from_line(lines[start_idx]))

        preamble = []
        if BLOCK_START_RE.match(lines[start_idx]):
            for comment in _collect_pre_operation_comments(lines, start_idx):
                if comment not in preamble:
                    preamble.append(comment)
            for comment in _collect_following_preamble_comments(lines, start_idx):
                if inline_tool_change_line and comment in start_line_comments:
                    continue
                if comment not in preamble:
                    preamble.append(comment)
        else:
            preamble = _collect_pre_operation_comments(lines, start_idx)
        if not inline_tool_change_line:
            for comment in start_line_comments:
                if comment not in preamble:
                    preamble.append(comment)

        n_line_op = _extract_operation_comment_from_n_line(lines[start_idx], block_number)
        if n_line_op:
            block_stats["operation_comment"] = n_line_op
        _apply_preamble_comments_to_block(block_stats, preamble)
        if inline_tool_change_line:
            _apply_inline_tool_comments_to_block(block_stats, start_line_comments)

        tool_change_seen_in_block = False
        for line_idx in range(start_idx, end_idx):
            line = lines[line_idx]
            clean_line = _clean_line(line)
            if not clean_line.strip():
                continue

            _apply_tool_line_comments(block_stats, line)

            if M6_RE.search(clean_line):
                tool_change_seen_in_block = True
                resolved_tool = _resolve_tool_at_m6(lines, line_idx)
                if resolved_tool:
                    block_stats["tool_number"] = resolved_tool
            elif _tool_number_from_g100_line(clean_line):
                if not _is_g100_safety_preload(lines, line_idx):
                    tool_change_seen_in_block = True
                    block_stats["tool_number"] = _tool_number_from_g100_line(clean_line)
            elif not block_stats["tool_number"] and not _is_preload_tool_line(
                clean_line, tool_change_seen_in_block
            ):
                tool_from_line = _tool_number_from_clean_line(clean_line)
                if tool_from_line:
                    block_stats["tool_number"] = tool_from_line

            for h_offset in _extract_tool_length_h_offsets(clean_line):
                block_stats["h_offsets"].add(h_offset)
            for d_offset in _extract_cutter_comp_d_offsets(clean_line):
                block_stats["d_offsets"].add(d_offset)
            for speed in S_RE.findall(clean_line):
                block_stats["spindle_speeds"].add(float(speed))
            for feed in F_RE.findall(clean_line):
                block_stats["feedrates"].add(float(feed))
            for coolant in COOLANT_RE.findall(clean_line):
                block_stats["coolant_states"].add("M" + coolant)
            for cycle in CANNED_CYCLE_RE.findall(clean_line):
                block_stats["canned_cycles"].add("G" + cycle)
            block_stats["work_offsets"].update(_collect_work_offsets(clean_line))

            for axis, axis_value in AXIS_RE.findall(clean_line):
                _update_axis(block_stats, axis, float(axis_value))

        if block_stats.get("operation_comment"):
            block_stats["operation_comment"] = clean_operation_comment(
                block_stats["operation_comment"], block_number
            )

        if block_stats.get("tool_description"):
            block_stats["tool_description"] = clean_tool_description(
                block_stats["tool_description"]
            )
            if not block_stats["tool_description"] or not _is_valid_tool_description(
                block_stats["tool_description"]
            ):
                block_stats["tool_description"] = None

        if block_stats.get("tool_comment"):
            block_stats["tool_comment"] = clean_tool_description(block_stats["tool_comment"])

        header_tool = header_tool_map.get(block_stats["tool_number"], {})
        block_stats["tool_description_from_header"] = header_tool.get("tool_description", "-")
        block_stats["h_offset_from_header"] = header_tool.get("h_offset", "-")
        block_stats["d_offset_from_header"] = header_tool.get("d_offset_register", "-")

        operation_blocks.append(
            {
                "block_number": block_stats["block_number"],
                "block_line": block_stats["block_line"],
                "tool_number": block_stats["tool_number"] or "-",
                "operation_comment": _format_comment(block_stats["operation_comment"]),
                "tool_comment": _format_comment(block_stats["tool_comment"]),
                "tool_description": _format_comment(block_stats["tool_description"]),
                "diameter_from_comment": _format_comment(block_stats["diameter_from_comment"]),
                "corner_radius_from_comment": _format_comment(block_stats["corner_radius_from_comment"]),
                "tool_description_from_header": block_stats["tool_description_from_header"],
                "h_offset": _format_str_set(block_stats["h_offsets"]),
                "h_offset_from_header": block_stats["h_offset_from_header"],
                "d_offset_used": _format_str_set(block_stats["d_offsets"]),
                "d_offset_from_header": block_stats["d_offset_from_header"],
                "spindle_speed": _format_float_set(block_stats["spindle_speeds"]),
                "feedrates": _format_float_set(block_stats["feedrates"]),
                "work_offsets": _format_str_set(block_stats["work_offsets"]),
                "coolant": _format_str_set(block_stats["coolant_states"]),
                "canned_cycles": _format_str_set(block_stats["canned_cycles"]),
                "min_x": _format_opt_float(block_stats["min_x"]),
                "max_x": _format_opt_float(block_stats["max_x"]),
                "min_y": _format_opt_float(block_stats["min_y"]),
                "max_y": _format_opt_float(block_stats["max_y"]),
                "min_z": _format_opt_float(block_stats["min_z"]),
                "max_z": _format_opt_float(block_stats["max_z"]),
                "d_offset": _format_str_set(block_stats["d_offsets"]),
            }
        )

    return operation_blocks


def parse_gcode(text):
    lines = text.splitlines()
    program_number = None
    units = None
    work_offsets = set()
    comments = []
    tools = {}
    tool_order = []
    current_tool = None

    for line_idx, raw_line in enumerate(lines):
        for comment in _extract_comments_from_line(raw_line):
            comments.append(comment)

        clean_line = _clean_line(raw_line)
        if not clean_line.strip():
            continue

        if program_number is None:
            program_match = PROGRAM_RE.search(clean_line)
            if program_match:
                program_number = "O" + program_match.group(1)

        unit_match = UNITS_RE.search(clean_line)
        if unit_match:
            units = "G" + unit_match.group(1)

        work_offsets.update(_collect_work_offsets(clean_line))

        for tool_code in TOOL_RE.findall(clean_line):
            _register_tool("T%d" % int(tool_code), tools, tool_order)

        if M6_RE.search(clean_line):
            resolved_tool = _resolve_tool_at_m6(lines, line_idx)
            if resolved_tool:
                current_tool = resolved_tool
                _register_tool(current_tool, tools, tool_order)
            elif current_tool is None:
                current_tool = "UNKNOWN"
                _register_tool(current_tool, tools, tool_order)

        active_tool = current_tool if current_tool is not None else "NO_TOOL"
        if active_tool not in tools:
            tools[active_tool] = _new_tool_stats(active_tool)
            tool_order.append(active_tool)

        tool_stats = tools[active_tool]

        for h_offset in _extract_tool_length_h_offsets(clean_line):
            tool_stats["h_offsets"].add(h_offset)
        for d_offset in D_RE.findall(clean_line):
            tool_stats["d_offsets"].add("D%d" % int(d_offset))
        for speed in S_RE.findall(clean_line):
            tool_stats["spindle_speeds"].add(float(speed))
        for feed in F_RE.findall(clean_line):
            tool_stats["feedrates"].add(float(feed))
        for coolant in COOLANT_RE.findall(clean_line):
            tool_stats["coolant_states"].add("M" + coolant)

        for axis, axis_value in AXIS_RE.findall(clean_line):
            _update_axis(tool_stats, axis, float(axis_value))

    tool_rows = []
    for tool in tool_order:
        stats = tools[tool]
        if tool == "NO_TOOL" and not _tool_has_data(stats):
            continue
        row = {
            "Tool": stats["tool"],
            "H offsets": _format_str_set(stats["h_offsets"]),
            "D offsets": _format_str_set(stats["d_offsets"]),
            "Spindle S": _format_float_set(stats["spindle_speeds"]),
            "Feed F": _format_float_set(stats["feedrates"]),
            "Coolant": _format_str_set(stats["coolant_states"]),
            "Min X": _format_opt_float(stats["min_x"]),
            "Max X": _format_opt_float(stats["max_x"]),
            "Min Y": _format_opt_float(stats["min_y"]),
            "Max Y": _format_opt_float(stats["max_y"]),
            "Min Z": _format_opt_float(stats["min_z"]),
            "Max Z": _format_opt_float(stats["max_z"]),
        }
        tool_rows.append(row)

    summary = {
        "program_number": program_number or "-",
        "units": units or "-",
        "work_offsets": ", ".join(sorted(work_offsets)) if work_offsets else "-",
    }

    program_header, header_tool_table = _parse_program_header_and_tool_table(lines)
    header_tool_map = {row["tool_number"]: row for row in header_tool_table}
    operation_blocks = _parse_operation_blocks(lines, header_tool_map)

    if program_header["program_number"] == "-" and program_number:
        program_header["program_number"] = program_number

    return {
        "summary": summary,
        "tool_rows": tool_rows,
        "comments": comments,
        "program_header": program_header,
        "header_tool_table": header_tool_table,
        "operation_blocks": operation_blocks,
    }

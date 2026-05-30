"""
DMG DMF / Mastercam Siemens 5-axis MPF profile.

GROUP_BEGIN operation sections, ``T="tool name"`` + ``M6``, standalone ``D#`` after tool change,
semicolon ``;T1 - description`` headers. Ignores ``SUPA D0`` approach moves.
"""
from __future__ import annotations

import re
from typing import Any

from gcode_parser import (
    BLOCK_START_RE,
    M6_RE,
    S_RE,
    _clean_line,
    _collect_work_offsets,
    _extract_comments_from_line,
    _extract_semicolon_comment,
    _format_comment,
    _format_float_set,
    _format_str_set,
    _parse_semicolon_tool_comment,
    clean_operation_comment,
    clean_tool_description,
)

GROUP_BEGIN_RE = re.compile(r'GROUP_BEGIN\s*\(\s*,"([^"]+)"', re.IGNORECASE)
GROUP_END_RE = re.compile(r"\bGROUP_END\b", re.IGNORECASE)
SIEMENS_T_STRING_RE = re.compile(r'T\s*=\s*"([^"]+)"', re.IGNORECASE)
STANDALONE_D_LINE_RE = re.compile(r"^\s*D(\d+)\s*$", re.IGNORECASE)

_DMG_HEADER_MARKERS = (
    "DMG_DMF",
    "DMG DMF",
    "DMG_DMU",
    "DMG_DMU_SIEMENS",
    "DMG_DMF_SIEMENS",
    "DMG_DUOBLOCK",
    "DMG_MONOBLOCK",
    "POST         - DMG",
)

# Never use as operation description (detection only).
_IGNORED_OPERATION_COMMENT_RE = re.compile(
    r"(?:^|\b)(?:CYCLE800|TRAORI|TRAFOOF|GROUP_BEGIN|GROUP_END|SUPA|PLANE\s+RESET|PLANE\s+SPATIAL)\b",
    re.IGNORECASE,
)
# Parenthesis payload from CYCLE800(1,"DMG",220000,...)
_CYCLE800_PARAM_COMMENT_RE = re.compile(
    r'^\s*\d+\s*,\s*"[A-Z0-9]+"\s*,',
    re.IGNORECASE,
)
_PROGRAM_NAME_COMMENT_RE = re.compile(
    r"(?:PROGRAM\s+NAME|MCAM\s+FILE)\s*[-–—]\s*(.+)",
    re.IGNORECASE,
)


def _is_supa_d0_line(clean_line: str) -> bool:
    """``G0 SUPA D0`` / ``SUPA D0`` — approach reset, not cutter comp D."""
    if not re.search(r"\bSUPA\b", clean_line, re.IGNORECASE):
        return False
    return bool(re.search(r"\bD0\b", clean_line, re.IGNORECASE))


def _standalone_tool_d_offset(clean_line: str) -> str | None:
    if _is_supa_d0_line(clean_line):
        return None
    match = STANDALONE_D_LINE_RE.match(clean_line.strip())
    if not match:
        return None
    num = int(match.group(1))
    if num <= 0:
        return None
    return "D%d" % num


def _is_ignored_operation_comment_text(text: str) -> bool:
    c = (text or "").strip()
    if not c:
        return True
    if _IGNORED_OPERATION_COMMENT_RE.search(c):
        return True
    if _CYCLE800_PARAM_COMMENT_RE.match(c):
        return True
    if _parse_semicolon_tool_comment(c):
        return True
    if re.match(r"^T\d+\s*[-–—]", c, re.IGNORECASE):
        return True
    if "," in c and re.search(r"\b\d+\s*,\s*\d", c):
        return True
    if re.search(r"\bG\d", c, re.IGNORECASE):
        return True
    return False


def _program_name_from_header(lines: list[str]) -> str | None:
    for raw in lines[:40]:
        semi = _extract_semicolon_comment(raw)
        if not semi:
            continue
        match = _PROGRAM_NAME_COMMENT_RE.search(semi)
        if match:
            name = match.group(1).strip().strip('"')
            if name:
                return clean_operation_comment(name) or name
    return None


def _semicolon_operation_comment_near(
    lines: list[str], start: int, end: int, group_op_name: str
) -> str | None:
    """Meaningful ``;`` operation comment in section (not tool/CYCLE800 lines)."""
    for j in range(start, min(end, start + 40)):
        semi = _extract_semicolon_comment(lines[j])
        if not semi or _is_ignored_operation_comment_text(semi):
            continue
        if group_op_name and semi.strip().upper() == group_op_name.strip().upper():
            continue
        cleaned = clean_operation_comment(semi, group_op_name)
        if cleaned:
            return cleaned
    return None


def _resolve_operation_comment(
    group_op_name: str,
    lines: list[str],
    start_idx: int,
    end_idx: int,
) -> str:
    """GROUP_BEGIN name > semicolon op comment > program name from header."""
    if group_op_name and group_op_name.strip() and group_op_name.strip() != "-":
        return group_op_name.strip()
    semi_op = _semicolon_operation_comment_near(lines, start_idx, end_idx, group_op_name)
    if semi_op:
        return semi_op
    header_name = _program_name_from_header(lines)
    if header_name:
        return header_name
    return "-"


def _semicolon_tool_meta(lines: list[str], start: int, end: int) -> dict[str, Any]:
    """Nearest ``;T# - description`` before tool change in section."""
    for j in range(start, min(end, start + 40)):
        semi = _extract_semicolon_comment(lines[j])
        if not semi:
            continue
        parsed = _parse_semicolon_tool_comment(semi)
        if parsed:
            return parsed
    return {}


def _block_number_in_section(lines: list[str], start: int, end: int) -> str:
    """Real ``N####`` block only — not GROUP_BEGIN operation names."""
    for j in range(start, end):
        match = BLOCK_START_RE.match(lines[j])
        if match:
            return match.group(1).upper()
    return "-"


def _tool_name_from_t_equals(lines: list[str], start: int, end: int) -> str | None:
    for j in range(start, min(end, start + 25)):
        clean = _clean_line(lines[j])
        match = SIEMENS_T_STRING_RE.search(clean)
        if match:
            name = match.group(1).strip()
            if name:
                return name
    return None


def is_dmg_dmf_siemens_5axis_profile(
    gcode_text: str,
    program_type: str | None = None,
) -> bool:
    """
    DMG / Mastercam Siemens 5-axis MPF when GROUP_BEGIN + 5-axis transforms are present.
    """
    from gcode_parser import PROGRAM_TYPE_MILLING

    if not (gcode_text or "").strip():
        return False
    if program_type is not None and program_type != PROGRAM_TYPE_MILLING:
        return False

    text_up = gcode_text.upper()
    has_dmg = any(m in text_up for m in _DMG_HEADER_MARKERS)
    has_siemens_mpf = bool(
        re.search(r"%_N_", text_up) or re.search(r";%_N_", text_up)
    )
    has_group = bool(GROUP_BEGIN_RE.search(gcode_text))
    has_5ax = bool(
        re.search(r"\bCYCLE800\b", text_up)
        or re.search(r"\bTRAORI\b", text_up)
    )
    has_m6 = bool(M6_RE.search(gcode_text))

    if not has_group or not has_5ax or not has_m6:
        return False
    return has_dmg or has_siemens_mpf or bool(SIEMENS_T_STRING_RE.search(gcode_text))


def dmg_profile_detection_reasons(gcode_text: str) -> list[str]:
    """Extra detection reasons when DMG Siemens profile matches."""
    reasons: list[str] = []
    text_up = gcode_text.upper()
    if re.search(r"%_N_|;%_N_", text_up):
        reasons.append("Found Siemens MPF semicolon header")
    if "CYCLE800" in text_up:
        reasons.append("Found CYCLE800 tilted work plane")
    if "TRAORI" in text_up:
        reasons.append("Found TRAORI / 5-axis transform")
    if GROUP_BEGIN_RE.search(gcode_text):
        reasons.append("Found GROUP_BEGIN operation sections")
    if SIEMENS_T_STRING_RE.search(gcode_text):
        reasons.append('Found T="tool name" Siemens tool assignment')
    return reasons


def parse_dmg_dmf_siemens_5axis(gcode_text: str) -> list[dict[str, Any]]:
    """One operation row per GROUP_BEGIN section, in file order."""
    lines = gcode_text.splitlines()
    starts: list[tuple[int, str]] = []
    for idx, raw in enumerate(lines):
        match = GROUP_BEGIN_RE.search(raw)
        if match:
            starts.append((idx, match.group(1).strip()))

    if not starts:
        return []

    blocks: list[dict[str, Any]] = []
    for seq, (start_idx, op_name) in enumerate(starts):
        end_idx = len(lines)
        if seq + 1 < len(starts):
            end_idx = starts[seq + 1][0]
        else:
            for j in range(start_idx + 1, len(lines)):
                if GROUP_END_RE.search(_clean_line(lines[j])):
                    end_idx = j
                    break

        tool_number = "-"
        tool_description = None
        d_offsets: set[str] = set()
        h_offsets: set[str] = set()
        work_offsets: set[str] = set()
        spindle_speeds: set[float] = set()
        operation_comment = _resolve_operation_comment(op_name, lines, start_idx, end_idx)

        semi_meta = _semicolon_tool_meta(lines, start_idx, end_idx)
        if semi_meta.get("tool_number"):
            tool_number = semi_meta["tool_number"]
        if semi_meta.get("tool_description"):
            tool_description = semi_meta["tool_description"]
        if semi_meta.get("d_offset"):
            d_offsets.add(semi_meta["d_offset"])

        t_name = _tool_name_from_t_equals(lines, start_idx, end_idx)
        if t_name:
            tool_description = clean_tool_description(t_name) or t_name

        for j in range(start_idx + 1, end_idx):
            clean = _clean_line(lines[j])
            if not clean.strip():
                continue

            if M6_RE.search(clean):
                if semi_meta.get("tool_number"):
                    tool_number = semi_meta["tool_number"]
                for back in range(j - 1, max(start_idx - 1, j - 15), -1):
                    semi = _extract_semicolon_comment(lines[back])
                    if semi:
                        parsed = _parse_semicolon_tool_comment(semi)
                        if parsed and parsed.get("tool_number"):
                            tool_number = parsed["tool_number"]
                            if not tool_description and parsed.get("tool_description"):
                                tool_description = parsed["tool_description"]
                            break

            d_standalone = _standalone_tool_d_offset(clean)
            if d_standalone:
                d_offsets.add(d_standalone)

            work_offsets.update(_collect_work_offsets(clean))
            for speed in S_RE.findall(clean):
                spindle_speeds.add(float(speed))

        if not tool_description and semi_meta.get("tool_description"):
            tool_description = semi_meta["tool_description"]

        block_number = _block_number_in_section(lines, start_idx, end_idx)

        blocks.append(
            {
                "sequence_index": seq,
                "block_number": block_number,
                "block_line": lines[start_idx].strip(),
                "tool_number": tool_number,
                "operation_comment": _format_comment(operation_comment),
                "tool_comment": _format_comment(semi_meta.get("tool_description")),
                "tool_description": _format_comment(tool_description),
                "tool_description_from_header": "-",
                "h_offset": _format_str_set(h_offsets) if h_offsets else "-",
                "h_offset_from_header": "-",
                "d_offset_used": _format_str_set(d_offsets),
                "d_offset_from_header": "-",
                "d_offset": _format_str_set(d_offsets),
                "spindle_speed": _format_float_set(spindle_speeds),
                "feedrates": "-",
                "work_offsets": _format_str_set(work_offsets),
                "coolant": "-",
                "canned_cycles": "-",
                "min_x": "-",
                "max_x": "-",
                "min_y": "-",
                "max_y": "-",
                "min_z": "-",
                "max_z": "-",
                "parser_profile": "dmg_dmf_siemens_5axis",
            }
        )

    return blocks

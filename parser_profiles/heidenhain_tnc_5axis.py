"""
HEIDENHAIN TNC / DMG DMF 5-axis milling profile.

``BEGIN PGM`` / ``TOOL CALL`` / ``CYCL DEF`` / ``M128`` posts — not Fanuc N-blocks or Siemens GROUP_BEGIN.
"""
from __future__ import annotations

import re
from typing import Any

from gcode_parser import (
    S_RE,
    _clean_line,
    _extract_semicolon_comment,
    _format_comment,
    _format_float_set,
    clean_operation_comment,
    clean_tool_description,
)

CONTROL_PROFILE_LABEL = "HEIDENHAIN TNC"

BEGIN_PGM_RE = re.compile(
    r"\bBEGIN\s+PGM\s+(.+?)(?:\s+(?:INCH|MM)\b|$)",
    re.IGNORECASE,
)
END_PGM_RE = re.compile(r"\bEND\s+PGM\b", re.IGNORECASE)
TOOL_CALL_RE = re.compile(
    r"\bTOOL\s+CALL\s+(\d+)\b",
    re.IGNORECASE,
)
PROGRAM_NAME_COMMENT_RE = re.compile(
    r"PROGRAM\s+NAME\s*[-–—]\s*(.+)",
    re.IGNORECASE,
)
CYCL_DEF_247_RE = re.compile(r"\bCYCL\s+DEF\s+247\b", re.IGNORECASE)
Q339_RE = re.compile(r"\bQ339\s*=\s*\+?(\d+)\b", re.IGNORECASE)


def _is_heidenhain_structure(gcode_text: str) -> bool:
    text_up = gcode_text.upper()
    if not re.search(r"\bBEGIN\s+PGM\b", text_up):
        return False
    if not TOOL_CALL_RE.search(gcode_text):
        return False
    if re.search(r"\bGROUP_BEGIN\b", text_up) and re.search(r"\bCYCLE800\b", text_up):
        return False
    return bool(
        re.search(r"\bCYCL\s+DEF\b", text_up)
        or re.search(r"\bM128\b", text_up)
        or re.search(r"\bPLANE\s+(?:RESET|SPATIAL)\b", text_up)
        or re.search(r"\bL\s+[XYZBC]", text_up)
    )


def is_heidenhain_tnc_5axis_profile(
    gcode_text: str,
    program_type: str | None = None,
) -> bool:
    from gcode_parser import PROGRAM_TYPE_MILLING

    if not (gcode_text or "").strip():
        return False
    if program_type is not None and program_type != PROGRAM_TYPE_MILLING:
        return False
    return _is_heidenhain_structure(gcode_text)


def heidenhain_profile_detection_reasons(gcode_text: str) -> list[str]:
    reasons: list[str] = []
    text_up = gcode_text.upper()
    if re.search(r"\bBEGIN\s+PGM\b", text_up) and re.search(r"\bEND\s+PGM\b", text_up):
        reasons.append("Found BEGIN PGM / END PGM HEIDENHAIN structure")
    elif re.search(r"\bBEGIN\s+PGM\b", text_up):
        reasons.append("Found BEGIN PGM HEIDENHAIN structure")
    if TOOL_CALL_RE.search(gcode_text):
        reasons.append("Found TOOL CALL")
    if re.search(r"\bCYCL\s+DEF\b", text_up):
        reasons.append("Found CYCL DEF")
    if re.search(r"\bM128\b", text_up):
        reasons.append("Found M128 TCPM / 5-axis control")
    if re.search(r"\bPLANE\s+(?:RESET|SPATIAL)\b", text_up):
        reasons.append("Found PLANE RESET / PLANE SPATIAL")
    if re.search(r"\bQ\d+\s*=", text_up):
        reasons.append("Found Q parameter assignments")
    if re.search(r"\bL\s+[XYZ]", text_up):
        reasons.append("Found L X/Y/Z HEIDENHAIN motion")
    return reasons


def _program_operation_name(gcode_text: str) -> str:
    for raw in gcode_text.splitlines():
        semi = _extract_semicolon_comment(raw)
        if semi:
            match = PROGRAM_NAME_COMMENT_RE.search(semi)
            if match:
                name = match.group(1).strip().strip('"')
                if name:
                    return clean_operation_comment(name) or name
        match = BEGIN_PGM_RE.search(raw)
        if match:
            name = match.group(1).strip()
            if name:
                return clean_operation_comment(name) or name
    return "-"


def _parse_heidenhain_tool_comment(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    line = text.strip().lstrip("*").strip()
    if line.startswith("-"):
        line = line[1:].strip()
    match = re.match(
        r"^\s*TOOL\s+(\d+)\s*[-–—]\s*(.+)$",
        line,
        re.IGNORECASE,
    )
    if not match:
        return None
    tool_num = int(match.group(1))
    rest = match.group(2).strip().strip('"')
    desc_parts: list[str] = []
    for part in re.split(r"\s*[-–—]\s*", rest):
        token = part.strip().strip('"')
        if not token:
            continue
        if token.upper().startswith("DIA"):
            continue
        if token.upper().startswith("CORNER"):
            continue
        desc_parts.append(token)
    description = " ".join(desc_parts).strip() if desc_parts else rest
    return {
        "tool_number": "T%d" % tool_num,
        "tool_description": clean_tool_description(description) or description or "-",
    }


def _tool_comment_near(lines: list[str], tool_call_idx: int, lookback: int = 25) -> dict[str, Any]:
    for j in range(tool_call_idx - 1, max(-1, tool_call_idx - lookback) - 1, -1):
        raw = lines[j].strip()
        if not raw:
            continue
        semi = _extract_semicolon_comment(lines[j])
        if semi:
            parsed = _parse_heidenhain_tool_comment(semi)
            if parsed:
                return parsed
        if raw.startswith("*"):
            parsed = _parse_heidenhain_tool_comment(raw)
            if parsed:
                return parsed
    return {}


def _datum_before(lines: list[str], end_idx: int) -> str | None:
    """Nearest ``CYCL DEF 247`` / ``Q339=+N`` before ``end_idx``."""
    blob_parts: list[str] = []
    for j in range(max(0, end_idx - 80), end_idx):
        blob_parts.append(lines[j])
        blob_parts.append(_extract_semicolon_comment(lines[j]) or "")
    blob = "\n".join(blob_parts)
    if not CYCL_DEF_247_RE.search(blob):
        return None
    matches = list(Q339_RE.finditer(blob))
    if not matches:
        return None
    return "DATUM %d" % int(matches[-1].group(1))


def _parse_tool_call_line(clean_line: str) -> dict[str, Any]:
    out: dict[str, Any] = {"tool_number": "-", "spindle_speeds": set()}
    match = TOOL_CALL_RE.search(clean_line)
    if match:
        out["tool_number"] = "T%d" % int(match.group(1))
    for speed in S_RE.findall(clean_line):
        out["spindle_speeds"].add(float(speed))
    return out


def parse_heidenhain_tnc_5axis(gcode_text: str) -> list[dict[str, Any]]:
    """One operation row per ``TOOL CALL``, in file order."""
    lines = gcode_text.splitlines()
    tool_call_indexes = [
        idx
        for idx, raw in enumerate(lines)
        if TOOL_CALL_RE.search(_clean_line(raw))
    ]
    if not tool_call_indexes:
        return []

    program_op = _program_operation_name(gcode_text)
    blocks: list[dict[str, Any]] = []

    for seq, start_idx in enumerate(tool_call_indexes):
        end_idx = tool_call_indexes[seq + 1] if seq + 1 < len(tool_call_indexes) else len(lines)
        for j in range(start_idx + 1, len(lines)):
            if END_PGM_RE.search(_clean_line(lines[j])):
                end_idx = j
                break

        call_info = _parse_tool_call_line(_clean_line(lines[start_idx]))
        tool_number = call_info["tool_number"]
        tool_description = None
        spindle_speeds = set(call_info.get("spindle_speeds") or [])

        comment_meta = _tool_comment_near(lines, start_idx)
        if comment_meta.get("tool_number"):
            tool_number = comment_meta["tool_number"]
        if comment_meta.get("tool_description"):
            tool_description = comment_meta["tool_description"]

        operation_comment = program_op
        datum = _datum_before(lines, start_idx) or _datum_before(lines, end_idx)

        for j in range(start_idx + 1, end_idx):
            clean = _clean_line(lines[j])
            if not clean.strip():
                continue
            for speed in S_RE.findall(clean):
                spindle_speeds.add(float(speed))

        blocks.append(
            {
                "sequence_index": seq,
                "block_number": "-",
                "block_line": lines[start_idx].strip(),
                "tool_number": tool_number,
                "operation_comment": _format_comment(operation_comment),
                "tool_comment": _format_comment(tool_description),
                "tool_description": _format_comment(tool_description),
                "tool_description_from_header": "-",
                "h_offset": "-",
                "h_offset_from_header": "-",
                "d_offset_used": "-",
                "d_offset_from_header": "-",
                "d_offset": "-",
                "spindle_speed": _format_float_set(spindle_speeds),
                "feedrates": "-",
                "work_offsets": datum if datum else "-",
                "coolant": "-",
                "canned_cycles": "-",
                "min_x": "-",
                "max_x": "-",
                "min_y": "-",
                "max_y": "-",
                "min_z": "-",
                "max_z": "-",
                "parser_profile": "heidenhain_tnc_5axis",
                "control_profile": CONTROL_PROFILE_LABEL,
            }
        )

    return blocks

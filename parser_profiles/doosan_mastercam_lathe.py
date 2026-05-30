"""
Doosan LYNX / Mastercam lathe mill-turn profile.

Lathe-style T0101 tool calls, live-tool G17/G19 sections, per-datum operation rows.
"""
from __future__ import annotations

import re
from typing import Any

from gcode_parser import (
    BLOCK_START_RE,
    G43_G44_RE,
    M6_RE,
    NUM_RE,
    S_RE,
    _clean_line,
    _collect_work_offsets,
    _extract_comments_from_line,
    _extract_cutter_comp_d_offsets,
    _extract_tool_length_h_offsets,
    _format_comment,
    _format_float_set,
    _format_opt_float,
    _format_str_set,
    _has_tool_word,
    clean_operation_comment,
    clean_tool_description,
)

_LATHE_TOOL_ON_LINE_RE = re.compile(
    r"\bT0*(\d{1,2})(\d{2})\b",
    re.IGNORECASE,
)
_G97_SPINDLE_RE = re.compile(r"\bG97\b.*?\bS" + NUM_RE, re.IGNORECASE)
_ROTARY_AXIS_MOTION_RE = re.compile(
    r"(?<![A-Z])([ABC])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?![A-Z0-9])",
    re.IGNORECASE,
)
_EXTENDED_WCS_RE = re.compile(
    r"\bG54\.1\s+P(\d+)\b",
    re.IGNORECASE,
)
_TOOL_OFFSET_COMMENT_RE = re.compile(
    r"^\s*TOOL\s*-\s*(\d+)\s+OFFSET\s*-\s*(\d+)",
    re.IGNORECASE,
)

_DOOSAN_HEADER_MARKERS = (
    "MCAM FILE",
    "MASTERCAM",
    "PROGRAM NAME",
    "NC FILE",
    "LATHE",
)

_IGNORE_PREAMBLE_MARKERS = (
    "PROGRAM NAME",
    "DATE=",
    "DATE -",
    "MCAM FILE",
    "NC FILE",
    "MATERIAL",
    "XFER PART",
    "TRANSFER PART",
    "G20",
    "G21",
    "%",
)

_2AXIS_IGNORE_COMMENT_MARKERS = (
    "POST CUSTOMIZATION",
    "TAILSTOCK",
    "ENGAGE TAILSTOCK",
    "RETRACT TAILSTOCK",
    "MISC OPS",
)


def _is_g28_h0_reset(clean_line: str) -> bool:
    return bool(re.search(r"\bG28\b", clean_line, re.IGNORECASE) and re.search(
        r"\bH0\b", clean_line, re.IGNORECASE
    ))


def _parse_lathe_tool_on_line(clean_line: str) -> dict[str, Any] | None:
    """``G0 T0101`` -> tool T1, lathe offset 1, display D1."""
    if not re.search(r"\bG0\s*T", clean_line, re.IGNORECASE):
        return None
    match = _LATHE_TOOL_ON_LINE_RE.search(clean_line)
    if not match:
        return None
    tool_num = int(match.group(1))
    offset_num = int(match.group(2))
    return {
        "tool_number": "T%d" % tool_num,
        "lathe_offset": offset_num,
        "d_offset": "D%d" % offset_num,
    }


def _is_lathe_tool_change_line(clean_line: str) -> bool:
    return _parse_lathe_tool_on_line(clean_line) is not None


def _parse_2axis_lathe_tool_on_line(clean_line: str) -> dict[str, Any] | None:
    """``G0 T0202`` -> display ``T0202``, remark ``Tool offset T02`` (2-axis profile only)."""
    if not re.search(r"\bG0\s*T", clean_line, re.IGNORECASE):
        return None
    match = _LATHE_TOOL_ON_LINE_RE.search(clean_line)
    if not match:
        return None
    tool_num = int(match.group(1))
    offset_num = int(match.group(2))
    if offset_num == 0:
        return None
    token_match = re.search(r"\b(T0[1-9]\d{2})\b", clean_line, re.IGNORECASE)
    tool_token = token_match.group(1).upper() if token_match else "T%02d%02d" % (tool_num, offset_num)
    return {
        "tool_number": tool_token,
        "lathe_offset": offset_num,
        "tool_station": tool_num,
        "remark": "Tool offset T%02d" % tool_num,
    }


def _is_active_lathe_tool_line(clean_line: str) -> bool:
    """``G0 T0202`` style active tool call; ignores ``T0200`` cancel (offset 00)."""
    return _parse_2axis_lathe_tool_on_line(clean_line) is not None


def _is_2axis_ignored_comment(comment: str) -> bool:
    """Ignore file/header/tailstock noise but keep ``LATHE TOOL`` tool-description comments."""
    u = comment.strip().upper()
    if not u or u == "%":
        return True
    if _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
        return False
    for marker in _IGNORE_PREAMBLE_MARKERS:
        if marker in u:
            return True
    if any(marker in u for marker in _2AXIS_IGNORE_COMMENT_MARKERS):
        return True
    if any(m in u for m in ("MCAM FILE", "NC FILE", "MASTERCAM", "PROGRAM NAME")):
        return True
    return False


def _is_2axis_tool_description_comment(comment: str) -> bool:
    if not comment or _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
        return False
    if _is_2axis_ignored_comment(comment):
        return False
    if _is_doosan_operation_comment(comment):
        return False
    return True


def _shorten_operation_description(tool_description: str | None) -> str | None:
    if not tool_description:
        return None
    text = re.sub(r"\s+", " ", tool_description.strip())
    if " - " in text:
        return text.split(" - ", 1)[0].strip()
    return text or None


def _is_doosan_header_comment(comment: str) -> bool:
    u = comment.strip().upper()
    return any(marker in u for marker in _DOOSAN_HEADER_MARKERS)


def _is_ignored_preamble_comment(comment: str) -> bool:
    u = comment.strip().upper()
    if not u or u == "%":
        return True
    if _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
        return False
    for marker in _IGNORE_PREAMBLE_MARKERS:
        if marker in u:
            return True
    return _is_doosan_header_comment(comment)


def _is_doosan_operation_comment(comment: str) -> bool:
    u = comment.strip().upper()
    if _is_ignored_preamble_comment(comment):
        return False
    if re.match(
        r"^(MACHINE|DRILL|SPOT|TAP|REAM|BORING|CONTOUR|SPLINE|PART OFF|CUT OFF|ROUGH|FINISH)\b",
        u,
    ):
        return True
    if any(
        phrase in u
        for phrase in (
            "USING Y-AXIS",
            "USING C-AXIS",
            "CROSS DRILL",
            "RIGHT SPINDLE",
            "LEFT SPINDLE",
        )
    ):
        return True
    return False


def _is_doosan_tool_description(comment: str) -> bool:
    if not comment or _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
        return False
    if _is_doosan_operation_comment(comment):
        return False
    if _is_ignored_preamble_comment(comment):
        return False
    return _has_tool_word(comment) or bool(
        re.search(r"ENDMILL|DRILL|SPOT|MILL|BORING|FACE|GROOVE", comment, re.IGNORECASE)
    )


def _primary_datum_from_line(clean_line: str) -> str | None:
    ext = _EXTENDED_WCS_RE.search(clean_line)
    if ext:
        return "G54.1 P%s" % int(ext.group(1))
    offsets = _collect_work_offsets(clean_line)
    if offsets:
        return sorted(offsets)[0]
    return None


def _collect_preamble_comments(lines: list[str], tool_idx: int, lookback: int = 24) -> list[str]:
    """
    Comments from the nearest ``(TOOL - N OFFSET - M)`` line up to (not including) ``G0 T####``.
    """
    tool_offset_line = None
    for j in range(tool_idx - 1, max(-1, tool_idx - lookback) - 1, -1):
        for comment in _extract_comments_from_line(lines[j]):
            if _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
                tool_offset_line = j
                break
        if tool_offset_line is not None:
            break
    if tool_offset_line is None:
        return []
    comments: list[str] = []
    for j in range(tool_offset_line, tool_idx):
        for comment in _extract_comments_from_line(lines[j]):
            c = comment.strip()
            if c:
                comments.append(c)
    return comments


def _is_2axis_section_operation_comment(comment: str) -> bool:
    """Short operation label after an N-block header, e.g. ``(ROUGH)`` or ``(DRILL)``."""
    c = comment.strip()
    if not c or _is_2axis_ignored_comment(c):
        return False
    if _TOOL_OFFSET_COMMENT_RE.match(c):
        return False
    if _is_2axis_tool_description_comment(c):
        return False
    u = c.upper()
    if re.match(
        r"^(ROUGH|DRILL|THREAD|FINISH|FACE|BORING|GROOVE|TURN|SPOT|TAP|REAM)\.?$",
        u,
    ):
        return True
    if _is_doosan_operation_comment(c):
        return True
    words = u.split()
    return 1 <= len(words) <= 3 and len(u) <= 40


def _find_2axis_n_header_line(
    lines: list[str], before_line: int, lookback: int = 24
) -> tuple[int | None, str | None]:
    """Nearest standalone N-block operation header above ``(TOOL - # OFFSET)``."""
    for j in range(before_line, max(-1, before_line - lookback) - 1, -1):
        raw = lines[j].strip()
        if not raw:
            continue
        if _is_active_lathe_tool_line(_clean_line(raw)):
            break
        match = BLOCK_START_RE.match(raw)
        if not match:
            continue
        remainder = raw[match.end() :].strip()
        if remainder and not remainder.startswith("("):
            if re.search(r"\b[XYZFGMT]\d", remainder, re.IGNORECASE):
                continue
            if re.search(r"[A-Z]\d", remainder, re.IGNORECASE):
                continue
        return j, match.group(1).upper()
    return None, None


def _operation_comment_between_n_and_tool_offset(
    lines: list[str], n_line: int, tool_offset_line: int
) -> str | None:
    for j in range(n_line + 1, tool_offset_line):
        for comment in _extract_comments_from_line(lines[j]):
            c = comment.strip()
            if not c or _is_2axis_ignored_comment(c):
                continue
            if _TOOL_OFFSET_COMMENT_RE.match(c):
                break
            if _is_2axis_section_operation_comment(c):
                return clean_operation_comment(c) or c
        else:
            continue
        break
    for comment in _extract_comments_from_line(lines[n_line]):
        c = comment.strip()
        if _is_2axis_section_operation_comment(c):
            return clean_operation_comment(c) or c
    return None


def _collect_2axis_section_preamble(
    lines: list[str], tool_idx: int, lookback: int = 30
) -> tuple[str | None, str | None, list[str]]:
    """
    N-block header, section operation comment, and TOOL-offset preamble before ``G0 T####``.
    """
    tool_offset_line = None
    for j in range(tool_idx - 1, max(-1, tool_idx - lookback) - 1, -1):
        for comment in _extract_comments_from_line(lines[j]):
            if _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
                tool_offset_line = j
                break
        if tool_offset_line is not None:
            break
    if tool_offset_line is None:
        return None, None, []

    n_line, block_number = _find_2axis_n_header_line(lines, tool_offset_line, lookback)
    section_operation = None
    if n_line is not None and block_number:
        section_operation = _operation_comment_between_n_and_tool_offset(
            lines, n_line, tool_offset_line
        )

    if not (block_number and section_operation):
        block_number = None
        section_operation = None

    preamble = _collect_preamble_comments(lines, tool_idx, lookback)
    return block_number, section_operation, preamble


def _parse_tool_preamble(
    preamble: list[str],
    tool_line_meta: dict[str, Any],
) -> dict[str, Any]:
    tool_number = tool_line_meta["tool_number"]
    lathe_offset = tool_line_meta["lathe_offset"]
    d_offset = tool_line_meta["d_offset"]
    tool_description = None
    operation_comment = None

    for comment in preamble:
        if _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
            m = _TOOL_OFFSET_COMMENT_RE.match(comment.strip())
            if m:
                tool_number = "T%d" % int(m.group(1))
                lathe_offset = int(m.group(2))
                d_offset = "D%d" % lathe_offset
            continue
        if _is_doosan_tool_description(comment) and not tool_description:
            tool_description = clean_tool_description(comment)
            continue
        if _is_doosan_operation_comment(comment) and not operation_comment:
            operation_comment = clean_operation_comment(comment)

    return {
        "tool_number": tool_number,
        "lathe_offset": lathe_offset,
        "d_offset": d_offset,
        "tool_description": tool_description,
        "operation_comment": operation_comment,
    }


def _emit_operation_runs(
    lines: list[str],
    segment_start: int,
    segment_end: int,
    base_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    """One row per work offset when the same tool/op repeats under G55, G56, …"""
    runs: list[dict[str, Any]] = []
    operation_comment = base_meta.get("operation_comment")
    tool_description = base_meta.get("tool_description")
    tool_number = base_meta.get("tool_number")
    lathe_offset = base_meta.get("lathe_offset")
    default_d = base_meta.get("d_offset")

    current_datum: str | None = None
    spindle_speeds: set[float] = set()
    h_offsets: set[str] = set()
    d_comp: set[str] = set()

    def _flush() -> None:
        nonlocal current_datum, spindle_speeds, h_offsets, d_comp
        if not current_datum:
            return
        d_used = set(d_comp)
        if not d_used and default_d:
            d_used.add(default_d)
        runs.append(
            {
                "tool_number": tool_number,
                "lathe_offset": lathe_offset,
                "operation_comment": operation_comment,
                "tool_description": tool_description,
                "work_offset": current_datum,
                "spindle_speeds": set(spindle_speeds),
                "h_offsets": set(h_offsets),
                "d_offsets": d_used,
            }
        )
        current_datum = None
        spindle_speeds = set()
        h_offsets = set()
        d_comp = set()

    for idx in range(segment_start, segment_end):
        raw = lines[idx]
        clean = _clean_line(raw)

        for comment in _extract_comments_from_line(raw):
            if _is_doosan_operation_comment(comment):
                cleaned_op = clean_operation_comment(comment)
                if not cleaned_op:
                    continue
                if current_datum is not None:
                    _flush()
                    operation_comment = cleaned_op
                elif not operation_comment:
                    operation_comment = cleaned_op

        datum = _primary_datum_from_line(clean)
        if datum:
            if current_datum and datum != current_datum:
                _flush()
            current_datum = datum

        if _G97_SPINDLE_RE.search(clean):
            for speed in S_RE.findall(clean):
                spindle_speeds.add(float(speed))

        if G43_G44_RE.search(clean) and not _is_g28_h0_reset(clean):
            for h in _extract_tool_length_h_offsets(clean):
                h_offsets.add(h)

        for d in _extract_cutter_comp_d_offsets(clean):
            d_comp.add(d)

    _flush()
    return runs


def _segment_body_end(lines: list[str], tool_idx: int, next_tool_idx: int) -> int:
    """Exclude the next tool's ``(TOOL - N OFFSET)`` preamble from this segment body."""
    for j in range(next_tool_idx - 1, tool_idx, -1):
        for comment in _extract_comments_from_line(lines[j]):
            if _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
                return j
        if _is_lathe_tool_change_line(_clean_line(lines[j])):
            break
    return next_tool_idx


def _run_to_operation_block(run: dict[str, Any], sequence_index: int) -> dict[str, Any]:
    wo = run.get("work_offset") or "-"
    d_offsets = run.get("d_offsets") or set()
    return {
        "sequence_index": sequence_index,
        "block_number": "-",
        "block_line": "-",
        "tool_number": run.get("tool_number") or "-",
        "operation_comment": _format_comment(run.get("operation_comment")),
        "tool_comment": _format_comment(run.get("tool_description")),
        "tool_description": _format_comment(run.get("tool_description")),
        "diameter_from_comment": "-",
        "corner_radius_from_comment": "-",
        "tool_description_from_header": "-",
        "h_offset": _format_str_set(run.get("h_offsets") or set()),
        "h_offset_from_header": "-",
        "d_offset_used": _format_str_set(d_offsets),
        "d_offset_from_header": "-",
        "spindle_speed": _format_float_set(run.get("spindle_speeds") or set()),
        "feedrates": "-",
        "work_offsets": wo if wo != "-" else "-",
        "coolant": "-",
        "canned_cycles": "-",
        "min_x": "-",
        "max_x": "-",
        "min_y": "-",
        "max_y": "-",
        "min_z": "-",
        "max_z": "-",
        "d_offset": _format_str_set(d_offsets),
        "lathe_offset": run.get("lathe_offset"),
        "parser_profile": "doosan_mastercam_lathe",
    }


def _parse_2axis_tool_preamble(
    preamble: list[str],
    tool_line_meta: dict[str, Any],
    block_number: str | None = None,
    section_operation_comment: str | None = None,
) -> dict[str, Any]:
    tool_number = tool_line_meta["tool_number"]
    lathe_offset = tool_line_meta["lathe_offset"]
    tool_description = None

    for comment in preamble:
        if _TOOL_OFFSET_COMMENT_RE.match(comment.strip()):
            m = _TOOL_OFFSET_COMMENT_RE.match(comment.strip())
            if m:
                lathe_offset = int(m.group(2))
            continue
        if _is_2axis_tool_description_comment(comment) and not tool_description:
            tool_description = clean_tool_description(comment)

    if block_number and section_operation_comment:
        operation_comment = section_operation_comment
    else:
        operation_comment = None

    return {
        "tool_number": tool_number,
        "lathe_offset": lathe_offset,
        "tool_description": tool_description,
        "operation_comment": operation_comment,
        "remark": tool_line_meta.get("remark"),
        "block_number": block_number,
    }


def _datum_for_tool_segment(
    lines: list[str],
    start_idx: int,
    end_idx: int,
) -> str:
    for idx in range(start_idx, min(end_idx, len(lines))):
        datum = _primary_datum_from_line(_clean_line(lines[idx]))
        if datum:
            return datum
    return "-"


def _h_offsets_for_tool_segment(
    lines: list[str],
    start_idx: int,
    end_idx: int,
) -> set[str]:
    found: set[str] = set()
    for idx in range(start_idx, min(end_idx, len(lines))):
        clean = _clean_line(lines[idx])
        if G43_G44_RE.search(clean) and not _is_g28_h0_reset(clean):
            for h in _extract_tool_length_h_offsets(clean):
                found.add(h)
    return found


def _2axis_run_to_operation_block(run: dict[str, Any], sequence_index: int) -> dict[str, Any]:
    wo = run.get("work_offset") or "-"
    block_number = run.get("block_number") or "-"
    return {
        "sequence_index": sequence_index,
        "block_number": block_number if block_number else "-",
        "block_line": "-",
        "tool_number": run.get("tool_number") or "-",
        "operation_comment": _format_comment(run.get("operation_comment")),
        "tool_comment": _format_comment(run.get("tool_description")),
        "tool_description": _format_comment(run.get("tool_description")),
        "diameter_from_comment": "-",
        "corner_radius_from_comment": "-",
        "tool_description_from_header": "-",
        "h_offset": "-",
        "h_offset_from_header": "-",
        "d_offset_used": "-",
        "d_offset_from_header": "-",
        "spindle_speed": "-",
        "feedrates": "-",
        "work_offsets": wo if wo != "-" else "-",
        "coolant": "-",
        "canned_cycles": "-",
        "min_x": "-",
        "max_x": "-",
        "min_y": "-",
        "max_y": "-",
        "min_z": "-",
        "max_z": "-",
        "d_offset": "-",
        "remark": run.get("remark") or "",
        "lathe_offset": run.get("lathe_offset"),
        "parser_profile": "doosan_mastercam_2axis_lathe",
    }


def is_doosan_mastercam_2axis_lathe_profile(
    gcode_text: str,
    program_type: str | None = None,
) -> bool:
    """
    Doosan / Mastercam 2-axis lathe (LYNX-style T0202 posts without live-tool milling).
    """
    from gcode_parser import (
        PROGRAM_TYPE_LATHE,
        PROGRAM_TYPE_MILLING,
        PROGRAM_TYPE_MILL_TURN,
        PROGRAM_TYPE_SWISS,
        PROGRAM_TYPE_UNKNOWN,
    )

    if not (gcode_text or "").strip():
        return False
    if program_type in (
        PROGRAM_TYPE_MILL_TURN,
        PROGRAM_TYPE_MILLING,
        PROGRAM_TYPE_SWISS,
    ):
        return False
    if program_type is not None and program_type not in (
        PROGRAM_TYPE_LATHE,
        PROGRAM_TYPE_UNKNOWN,
    ):
        return False

    text_up = gcode_text.upper()
    if not any(m in text_up for m in _DOOSAN_HEADER_MARKERS):
        return False

    lines = gcode_text.splitlines()
    clean_lines = [_clean_line(ln) for ln in lines if ln.strip()]
    clean_blob = "\n".join(clean_lines)

    if M6_RE.search(clean_blob):
        return False
    if is_doosan_mastercam_lathe_millturn_profile(gcode_text, PROGRAM_TYPE_MILL_TURN):
        return False

    active_tools = sum(1 for ln in clean_lines if _is_active_lathe_tool_line(ln))
    if active_tools < 1:
        return False

    if re.search(r"\bG1[79]\b", clean_blob):
        return False

    return True


def parse_doosan_mastercam_2axis_lathe(gcode_text: str) -> list[dict[str, Any]]:
    """One operation row per active ``G0 T####`` lathe tool call (offset non-zero)."""
    lines = gcode_text.splitlines()
    tool_indexes: list[int] = []
    for idx, raw in enumerate(lines):
        if _is_active_lathe_tool_line(_clean_line(raw)):
            tool_indexes.append(idx)

    if not tool_indexes:
        return []

    operation_blocks: list[dict[str, Any]] = []
    for sequence_index, tool_idx in enumerate(tool_indexes):
        next_tool_idx = (
            tool_indexes[sequence_index + 1]
            if sequence_index + 1 < len(tool_indexes)
            else len(lines)
        )
        tool_line_meta = _parse_2axis_lathe_tool_on_line(_clean_line(lines[tool_idx]))
        if not tool_line_meta:
            continue
        block_number, section_operation, preamble = _collect_2axis_section_preamble(
            lines, tool_idx
        )
        meta = _parse_2axis_tool_preamble(
            preamble, tool_line_meta, block_number, section_operation
        )
        work_offset = _datum_for_tool_segment(lines, tool_idx, next_tool_idx)
        run = {
            "tool_number": meta["tool_number"],
            "lathe_offset": meta["lathe_offset"],
            "operation_comment": meta.get("operation_comment"),
            "tool_description": meta.get("tool_description"),
            "work_offset": work_offset,
            "remark": meta.get("remark"),
            "block_number": meta.get("block_number"),
        }
        operation_blocks.append(_2axis_run_to_operation_block(run, sequence_index))

    return operation_blocks


def is_doosan_mastercam_lathe_millturn_profile(
    gcode_text: str,
    program_type: str | None = None,
) -> bool:
    """
    Strong clues for Doosan LYNX / Mastercam lathe mill-turn posts.
    When ``program_type`` is supplied, it must be Mill-Turn.
    """
    from gcode_parser import PROGRAM_TYPE_MILL_TURN

    if not (gcode_text or "").strip():
        return False
    if program_type is not None and program_type != PROGRAM_TYPE_MILL_TURN:
        return False

    text_up = gcode_text.upper()
    has_header = any(m in text_up for m in _DOOSAN_HEADER_MARKERS)
    if not has_header:
        return False

    lines = gcode_text.splitlines()
    clean_lines = [_clean_line(ln) for ln in lines if ln.strip()]
    clean_blob = "\n".join(clean_lines)

    lathe_tool_lines = sum(1 for ln in clean_lines if _is_lathe_tool_change_line(ln))
    if lathe_tool_lines < 1:
        return False

    if M6_RE.search(clean_blob):
        return False

    has_plane = bool(re.search(r"\bG1[789]\b", clean_blob))
    has_y = bool(re.search(r"\bY", clean_blob, re.IGNORECASE))
    has_rotary_word = bool(
        _ROTARY_AXIS_MOTION_RE.search(clean_blob)
        or re.search(r"\b[ABC][-+]?(?:\d|\.)", clean_blob, re.IGNORECASE)
    )

    return (
        lathe_tool_lines >= 1
        and has_header
        and not M6_RE.search(clean_blob)
        and has_plane
    )


def parse_doosan_mastercam_lathe_millturn(gcode_text: str) -> list[dict[str, Any]]:
    """Build operation blocks for Doosan/Mastercam lathe mill-turn programs."""
    lines = gcode_text.splitlines()
    tool_indexes: list[int] = []
    for idx, raw in enumerate(lines):
        if _is_lathe_tool_change_line(_clean_line(raw)):
            tool_indexes.append(idx)

    if not tool_indexes:
        return []

    operation_blocks: list[dict[str, Any]] = []
    sequence_index = 0

    for k, tool_idx in enumerate(tool_indexes):
        next_tool_idx = tool_indexes[k + 1] if k + 1 < len(tool_indexes) else len(lines)
        segment_end = _segment_body_end(lines, tool_idx, next_tool_idx)
        tool_line_meta = _parse_lathe_tool_on_line(_clean_line(lines[tool_idx]))
        if not tool_line_meta:
            continue
        preamble = _collect_preamble_comments(lines, tool_idx)
        base_meta = _parse_tool_preamble(preamble, tool_line_meta)
        runs = _emit_operation_runs(lines, tool_idx + 1, segment_end, base_meta)
        for run in runs:
            operation_blocks.append(_run_to_operation_block(run, sequence_index))
            sequence_index += 1

    return operation_blocks


def doosan_profile_detection_reasons(gcode_text: str) -> list[str]:
    """Extra reasons for program-type UI when this profile matches."""
    reasons: list[str] = []
    if not is_doosan_mastercam_lathe_millturn_profile(gcode_text):
        return reasons
    text_up = gcode_text.upper()
    if "MCAM FILE" in text_up or "MASTERCAM" in text_up:
        reasons.append("Found Mastercam lathe post header (MCAM FILE)")
    lines = [_clean_line(ln) for ln in gcode_text.splitlines() if ln.strip()]
    if sum(1 for ln in lines if _is_lathe_tool_change_line(ln)) >= 1:
        reasons.append("Found lathe-style T0101/T0202 tool calls")
    if re.search(r"\bG1[79]\b", "\n".join(lines)):
        reasons.append("Found G17/G19 live-tool plane selects")
    if re.search(r"\bY", "\n".join(lines), re.IGNORECASE):
        reasons.append("Found Y-axis live-tool motion")
    if re.search(r"\bC\d", "\n".join(lines), re.IGNORECASE):
        reasons.append("Found C-axis motion")
    if "RIGHT SPINDLE" in text_up or "LEFT SPINDLE" in text_up:
        reasons.append("Found left/right spindle comments")
    if not M6_RE.search("\n".join(lines)):
        reasons.append("No M6 tool changes (lathe-style T#### tools)")
    return reasons

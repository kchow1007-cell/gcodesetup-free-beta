#!/usr/bin/env python3
"""
Parser regression tests — compare key fields against expected JSON fixtures.

Usage:
    python run_parser_tests.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from gcode_parser import detect_program_type, parse_gcode

ROOT = Path(__file__).resolve().parent
TESTS_DIR = ROOT / "parser_tests"
PROGRAM_TYPE_DIR = TESTS_DIR / "program_type"

CNC_EXTENSIONS = {
    ".nc",
    ".txt",
    ".tap",
    ".gcode",
    ".mpf",
    ".min",
    ".eia",
    ".cnc",
    ".h",
}

BLOCK_FIELDS = (
    "block_number",
    "tool_number",
    "operation_comment",
    "tool_description",
    "h_offset",
    "d_offset",
    "work_offsets",
)


def _normalize_d_offset_set(value: str) -> str:
    """Compare D offsets regardless of comma order."""
    text = (value or "-").strip()
    if not text or text == "-":
        return "-"
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return ", ".join(sorted(parts))


def _extract_actual(result: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for block in result.get("operation_blocks") or []:
        d_val = block.get("d_offset_used") or block.get("d_offset") or "-"
        blocks.append(
            {
                "block_number": block.get("block_number", "-"),
                "tool_number": block.get("tool_number", "-"),
                "operation_comment": block.get("operation_comment", "-"),
                "tool_description": block.get("tool_description", "-"),
                "h_offset": block.get("h_offset", "-"),
                "d_offset": d_val,
                "work_offsets": block.get("work_offsets", "-"),
            }
        )
    summary = result.get("summary") or {}
    return {
        "program_number": summary.get("program_number", "-"),
        "operation_blocks": blocks,
    }


def _discover_tests() -> list[tuple[Path, Path]]:
    cases: list[tuple[Path, Path]] = []
    if not TESTS_DIR.is_dir():
        return cases
    for cnc_path in sorted(TESTS_DIR.rglob("*")):
        if not cnc_path.is_file():
            continue
        if cnc_path.suffix.lower() not in CNC_EXTENSIONS:
            continue
        expected_path = cnc_path.with_suffix(".expected.json")
        if expected_path.is_file():
            cases.append((cnc_path, expected_path))
    return cases


def _compare_block_field(
    test_name: str,
    block_idx: int,
    field: str,
    expected: Any,
    actual: Any,
) -> list[str]:
    exp = expected if expected is not None else "-"
    act = actual if actual is not None else "-"
    if field == "d_offset":
        exp = _normalize_d_offset_set(str(exp))
        act = _normalize_d_offset_set(str(act))
    if exp != act:
        label = f"block[{block_idx}].{field}"
        return [f"{test_name}: {label} expected {exp!r}, got {act!r}"]
    return []


def _read_fixture_gcode(
    cnc_path: Path, expected_path: Path, expected: dict[str, Any]
) -> tuple[str | None, str | None]:
    """Read G-code from optional ``source`` (relative to expected JSON) or the CNC fixture file."""
    source_rel = expected.get("source")
    if source_rel:
        source_path = (expected_path.parent / source_rel).resolve()
        try:
            return source_path.read_text(encoding="utf-8", errors="replace"), None
        except OSError as exc:
            return None, f"could not read source {source_path}: {exc}"
    try:
        return cnc_path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return None, f"could not read CNC file: {exc}"


def _compare_block_field_contains(
    test_name: str,
    block_idx: int,
    field: str,
    substring: str,
    actual: str,
) -> list[str]:
    act = (actual if actual is not None else "-").strip()
    if substring not in act:
        return [
            f"{test_name}: block[{block_idx}].{field} expected to contain {substring!r}, got {act!r}"
        ]
    return []


def _compare_regression_guards(
    test_name: str, expected: dict[str, Any], act_blocks: list[dict[str, Any]]
) -> list[str]:
    """Optional fixture guards (forbidden tools/blocks, no placeholder tool rows)."""
    errors: list[str] = []
    act_tools = [str(b.get("tool_number", "-")).strip() for b in act_blocks]
    act_blocks_nums = [str(b.get("block_number", "-")).strip().upper() for b in act_blocks]

    for tool in expected.get("forbidden_tool_numbers") or []:
        if tool in act_tools:
            errors.append(f"{test_name}: must not include tool_number {tool!r}")

    for block in expected.get("forbidden_block_numbers") or []:
        bn = str(block).strip().upper()
        if bn in act_blocks_nums:
            errors.append(f"{test_name}: must not include block_number {bn!r}")

    placeholder = expected.get("forbidden_tool_placeholder")
    if placeholder is not None and placeholder in act_tools:
        errors.append(
            f"{test_name}: must not include placeholder tool_number {placeholder!r} "
            f"(blank fallback row)"
        )

    min_blocks = expected.get("require_min_operation_blocks")
    if min_blocks is not None and len(act_blocks) < int(min_blocks):
        errors.append(
            f"{test_name}: require at least {min_blocks} operation_blocks, got {len(act_blocks)}"
        )

    return errors


def _compare_test(cnc_path: Path, expected_path: Path) -> tuple[bool, list[str]]:
    rel = cnc_path.relative_to(TESTS_DIR)
    test_name = str(rel).replace("\\", "/")
    errors: list[str] = []

    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"{test_name}: could not read expected JSON: {exc}"]

    text, read_err = _read_fixture_gcode(cnc_path, expected_path, expected)
    if read_err:
        return False, [f"{test_name}: {read_err}"]

    actual = _extract_actual(parse_gcode(text))

    if actual.get("program_number") != expected.get("program_number"):
        errors.append(
            f"{test_name}: program_number expected {expected.get('program_number')!r}, "
            f"got {actual.get('program_number')!r}"
        )

    exp_blocks = expected.get("operation_blocks") or []
    act_blocks = actual.get("operation_blocks") or []
    if len(exp_blocks) != len(act_blocks):
        errors.append(
            f"{test_name}: operation_blocks count expected {len(exp_blocks)}, got {len(act_blocks)}"
        )

    errors.extend(_compare_regression_guards(test_name, expected, act_blocks))

    for idx, exp_block in enumerate(exp_blocks):
        if idx >= len(act_blocks):
            break
        act_block = act_blocks[idx]
        for field in BLOCK_FIELDS:
            if field == "tool_description" and exp_block.get("tool_description_contains"):
                errors.extend(
                    _compare_block_field_contains(
                        test_name,
                        idx,
                        field,
                        str(exp_block["tool_description_contains"]),
                        act_block.get(field),
                    )
                )
                continue
            errors.extend(
                _compare_block_field(
                    test_name,
                    idx,
                    field,
                    exp_block.get(field),
                    act_block.get(field),
                )
            )

    return (len(errors) == 0, errors)


def _discover_program_type_tests() -> list[tuple[Path, Path]]:
    cases: list[tuple[Path, Path]] = []
    if not PROGRAM_TYPE_DIR.is_dir():
        return cases
    for expected_path in sorted(PROGRAM_TYPE_DIR.glob("*.expected.json")):
        cases.append((expected_path, expected_path))
    return cases


def _compare_program_type_test(expected_path: Path) -> tuple[bool, list[str]]:
    rel = expected_path.relative_to(TESTS_DIR)
    test_name = str(rel).replace("\\", "/")
    errors: list[str] = []
    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"{test_name}: could not read expected JSON: {exc}"]

    source_rel = expected.get("source")
    if not source_rel:
        return False, [f"{test_name}: missing 'source' path"]
    source_path = (expected_path.parent / source_rel).resolve()
    try:
        text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, [f"{test_name}: could not read source {source_path}: {exc}"]

    actual = detect_program_type(text)
    for key in ("program_type", "milling_type", "lathe_type", "confidence", "control_profile"):
        if key in expected and actual.get(key) != expected[key]:
            errors.append(
                f"{test_name}: {key} expected {expected[key]!r}, got {actual.get(key)!r}"
            )
    for fragment in expected.get("reasons_contains") or []:
        reasons = actual.get("reasons") or []
        if not any(fragment in r for r in reasons):
            errors.append(
                f"{test_name}: reasons missing fragment {fragment!r} (got {reasons!r})"
            )
    return (len(errors) == 0, errors)


def main() -> int:
    cases = _discover_tests()
    pt_cases = _discover_program_type_tests()
    if not cases and not pt_cases:
        print(f"No tests found under {TESTS_DIR}")
        return 1

    passed = 0
    failed = 0

    for expected_path, _ in pt_cases:
        ok, errors = _compare_program_type_test(expected_path)
        label = str(expected_path.relative_to(TESTS_DIR)).replace("\\", "/")
        if ok:
            print(f"PASS  {label}")
            passed += 1
        else:
            print(f"FAIL  {label}")
            for err in errors:
                print(f"      {err}")
            failed += 1

    for cnc_path, expected_path in cases:
        ok, errors = _compare_test(cnc_path, expected_path)
        rel = cnc_path.relative_to(TESTS_DIR)
        label = str(rel).replace("\\", "/")
        if ok:
            print(f"PASS  {label}")
            passed += 1
        else:
            print(f"FAIL  {label}")
            for err in errors:
                print(f"      {err}")
            failed += 1

    print()
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

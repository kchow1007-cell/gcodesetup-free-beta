# GcodeSetup AI Changelog

This file records AI-assisted changes, decisions, and testing notes.

Purpose:
- Track what was changed.
- Help future Cursor agents understand recent work.
- Avoid repeating old fixes.
- Make debugging easier if something breaks later.

---

# How to Use This Changelog

After every AI-assisted code change, add a new entry at the top.

Use this format:

## YYYY-MM-DD — Short Task Title

### Task
Briefly describe what the user asked for.

### Files Changed
- file_name.py
- another_file.py

### What Changed
- Bullet point summary of actual changes.

### What Was Not Changed
- Parser logic unchanged, if applicable.
- UI unchanged, if applicable.
- Setup sheet layout unchanged, if applicable.

### Test Notes
- Sample tested:
- Expected:
- Actual:
- Pass/Fail:

### Follow-Up
- Any remaining issue or next step.

---

## 2026-05-29 — Streamlit Cloud ImportError Fix (home.py)

### Task
Fix Streamlit Cloud `ImportError: cannot import name 'MILLING_TYPE_3_AXIS' from 'gcode_parser'` by removing missing constant imports from `pages/home.py`.

### Files Changed
- `pages/home.py`
- `CHANGELOG_AI.md`

### What Changed
- Removed `MILLING_TYPE_*` imports from `pages/home.py`.
- Replaced `_MANUAL_PROGRAM_TYPE_MAP` milling subtype values with plain strings (`"3-Axis Milling"`, etc.).

### What Was Not Changed
- `gcode_parser.py` unchanged (no fake constants added).
- Parser, detection, setup sheet, and operation row logic unchanged.

### Test Notes
- `from gcode_parser import ...` (home.py imports) succeeds locally.
- Streamlit app starts without ImportError.

### Follow-Up
- Commit `pages/home.py` (and `CHANGELOG_AI.md` if tracking docs) to GitHub for Streamlit Cloud redeploy.

---

## 2026-05-29 — Fanuc/Haas Dense N-Block Milling Operation Rows

### Task
Fix Fanuc/Haas milling parser so programs with N numbers on nearly every line (e.g. HAAS UMC 500) do not create extra operation rows from non-tool-change N blocks or machine-state comments.

### Files Changed
- `gcode_parser.py`
- `parser_tests/haas_umc500/umc500_dense_n.txt`
- `parser_tests/haas_umc500/umc500_dense_n.expected.json`
- `CHANGELOG_AI.md`

### What Changed
- Added dense N-block detection (`_program_has_dense_n_blocks`) for Haas/Fanuc posts with many N lines but few N-line tool changes.
- In dense mode, operation rows start only from N lines with `T# M06` / `T# M6` (or G100 tool change), not from preamble N blocks or machine-state comments.
- Ignored header/machine comments: MCAM FILE, C-AXIS/B-AXIS LOCK/UNLOCK, etc.
- Extended H offset extraction to include Haas `G234 H#` (TCP) lines.
- Added regression fixture for UMC 500-style dense N program (single row at `N130 T1 M06`).

### What Was Not Changed
- UI and setup sheet layout unchanged.
- Lathe, Siemens/DMG, HEIDENHAIN, Brother, Makino, Fusion parsers unchanged for non-dense programs.
- Program type detection unchanged.

### Test Notes
- Sample: `Sample gcode UMC 500.txt` — 1 row, N130, T1, H1, G54, tool description only
- Regression: `python run_parser_tests.py` — 25 passed

### Follow-Up
- None.

---

## 2026-05-29 — Doosan 2-Axis Lathe Operation Comment Fallback

### Task
When no N-block + operation comment header exists, leave Block# and Operation Comment blank instead of using shortened tool description.

### Files Changed
- `parser_profiles/doosan_mastercam_lathe.py`
- `parser_tests/doosan_2axis/doosan_210_2axis.txt`
- `parser_tests/doosan_2axis/doosan_210_2axis.expected.json`
- `CHANGELOG_AI.md`

### What Changed
- Block# and Operation Comment only set when both N-block and section operation comment are found.
- Removed fallback that copied shortened tool description into Operation Comment.
- Updated main 2-axis fixture: first two ops have `N201`/`ROUGH` and `N801`/`DRILL`; later ops have `-` for Block# and Operation Comment.

### What Was Not Changed
- UI, setup sheet layout, and other parser profiles unchanged.
- Tool#, Tool Description, H/D blank, and Remark formatting unchanged.

### Test Notes
- Rows with N header: Block# + Operation Comment filled.
- Rows without N header: Block# `-`, Operation Comment `-`, Tool Description still filled.
- Pass/Fail: Pass (`python run_parser_tests.py`)

### Follow-Up
- None.

---

## 2026-05-29 — Doosan 2-Axis Lathe N-Block Operation Headers

### Task
Detect N-block operation headers and section operation comments before lathe tool calls (e.g. `N201` / `(ROUGH)` before `G0 T0202`).

### Files Changed
- `parser_profiles/doosan_mastercam_lathe.py`
- `parser_tests/doosan_2axis/doosan_210_2axis_n_headers.txt`
- `parser_tests/doosan_2axis/doosan_210_2axis_n_headers.expected.json`
- `CHANGELOG_AI.md`

### What Changed
- Added `_collect_2axis_section_preamble()` to look backward for N-block, operation comment, TOOL/OFFSET, and tool description.
- Block# set to `N201`, `N801`, etc.; Operation Comment from `(ROUGH)`, `(DRILL)`, etc.
- Fallback unchanged when no N-block header (shortened tool description as Operation Comment, Block# `-`).
- Added regression fixture for N-header format.

### What Was Not Changed
- UI and setup sheet layout unchanged.
- Milling, Siemens/DMG, HEIDENHAIN, and mill-turn parsers unchanged.
- 2-axis Tool#, H/D blank, and Remark formatting unchanged.

### Test Notes
- With N headers: Block# `N201`/`N801`, Operation Comment `ROUGH`/`DRILL`
- Without N headers: `doosan_210_2axis.txt` still uses fallback (Block# `-`, shortened op comment)
- Pass/Fail: Pass (`python run_parser_tests.py`)

### Follow-Up
- None.

---

## 2026-05-29 — Doosan 2-Axis Lathe Output Formatting

### Task
Update 2-axis lathe parser display: full tool token in Tool# (`T0202`), blank H/D offsets, Remark with `Tool offset T02` style text.

### Files Changed
- `parser_profiles/doosan_mastercam_lathe.py`
- `one_page_setup_sheet.py` (map `remark` from operation blocks to Remark column)
- `parser_tests/doosan_2axis/doosan_210_2axis.expected.json`
- `CHANGELOG_AI.md`

### What Changed
- Added `_parse_2axis_lathe_tool_on_line()` for `T0202`-style Tool# and `Tool offset T##` remark.
- 2-axis blocks emit `d_offset` / `h_offset` as `-`; remark on operation block.
- `default_operation_editor_rows` reads `ob.get("remark")` for Remark column.
- Updated regression fixture tool numbers and D offsets.

### What Was Not Changed
- UI layout unchanged.
- Milling, Siemens/DMG, HEIDENHAIN, and mill-turn parsers unchanged.
- Detection logic unchanged.

### Test Notes
- Sample: `Doosan 210 2 axis testing.txt`
- Expected: T0202/T0808/…, H/D `-`, Remark `Tool offset T02` etc.
- Pass/Fail: Pass (`python run_parser_tests.py` — 23 passed)

### Follow-Up
- None.

---

## 2026-05-29 — Doosan / Mastercam 2-Axis Lathe Parser

### Task
Add parser support for Doosan / Mastercam 2-axis lathe format (`Doosan 210 2 axis testing.txt`) with one operation row per active `G0 T####` tool call.

### Files Changed
- `parser_profiles/doosan_mastercam_lathe.py`
- `gcode_parser.py` (profile routing in `_select_operation_blocks` only)
- `parser_tests/doosan_2axis/doosan_210_2axis.txt`
- `parser_tests/doosan_2axis/doosan_210_2axis.expected.json`
- `CHANGELOG_AI.md`

### What Changed
- Added `is_doosan_mastercam_2axis_lathe_profile()` and `parse_doosan_mastercam_2axis_lathe()`.
- Active tool calls (`T0202`, `T0808`, …) create rows; cancel calls (`T0200`, `T0800`, …) are ignored.
- Tool description from preamble comment after `(TOOL - N OFFSET - M)`; operation description shortened before first ` - `.
- D offset from lathe offset pair (`T0202` → `D2`); H blank unless G43/G44 present; N sequence blank.
- Routed 2-axis profile before mill-turn in `_select_operation_blocks`.
- Added parser regression fixture with five expected rows (T2, T8, T2, T12, T3).

### What Was Not Changed
- UI unchanged.
- Setup sheet layout unchanged.
- Milling, Siemens/DMG, and HEIDENHAIN parser profiles unchanged.
- Doosan mill-turn parsing unchanged.
- `detect_program_type` logic unchanged (already classified this sample as 2-Axis Lathe).

### Test Notes
- Sample tested: `Doosan 210 2 axis testing.txt`
- Expected: 5 rows, G54, T2/T8/T12/T3, lathe tool descriptions and shortened operation names
- Actual: Matches expected; detection `Lathe / Turning` / `2-Axis Lathe` / High
- Pass/Fail: Pass (`python run_parser_tests.py` — 23 passed)

### Follow-Up
- None.

---

# Current Baseline Notes

## 2026-05-29 — AI Context System Created

### Task
Created AI handover documentation system for GcodeSetup so future Cursor agents can work with less context loss.

### Files Changed
- AI_CONTEXT.md
- CURSOR_RULES.md
- TEST_CASES.md
- CHANGELOG_AI.md

### What Changed
- Added main project context file.
- Added Cursor behavior rules.
- Added parser/detection regression test cases.
- Added AI changelog template.

### What Was Not Changed
- No Python files changed.
- No parser logic changed.
- No UI changed.
- No setup sheet layout changed.

### Test Notes
- No app test required because only markdown documentation files were created/updated.

### Follow-Up
- Future Cursor agents should read AI_CONTEXT.md, CURSOR_RULES.md, TEST_CASES.md, and CHANGELOG_AI.md before editing code.
- After future code changes, update CHANGELOG_AI.md with the actual work performed.

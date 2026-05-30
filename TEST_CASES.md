# GcodeSetup Parser Test Cases

This file records expected parser/detection behavior for sample CNC programs.

Purpose:
- Prevent future Cursor agents from breaking working formats.
- Give clear expected output before changing parser/detection logic.
- Use this as a regression checklist after parser updates.

## General Rule

After any parser or detection change, test:
1. The new sample related to the change.
2. At least one existing milling sample.
3. At least one existing lathe or mill-turn sample if lathe logic was touched.
4. At least one Siemens/DMG or 5-axis sample if 5-axis logic was touched.

---

# Detection Test Cases

## 1. Fanuc / Haas 3-Axis Milling

Expected detection:
- Program Type: Milling
- Milling Type: 3-Axis Milling
- Confidence: High or Medium depending evidence

Expected clues:
- T# M6 or T#M6
- G43 H offset
- G54/G55 work offset
- G17
- X/Y/Z motion
- No rotary axis motion

Should not detect as:
- Mill-Turn
- Lathe / Turning

---

## 2. Basic Fanuc Milling Without N Block Comments

Expected detection:
- Program Type: Milling
- Milling Type: 3-Axis Milling

Expected behavior:
- Treat each M6 tool change as an operation if no N block operation marker exists.
- Keep N sequence # blank if no useful N block exists.
- Use nearby operation/tool comments when available.

Should not:
- Invent fake N sequence numbers.
- Sort by tool number automatically.

---

## 3. Brother G100 Milling

Expected detection:
- Program Type: Milling
- Milling Type: 4-Axis or 5-Axis depending rotary evidence

Expected parser behavior:
- Treat G100 T# as tool change.
- Extract tool number from G100 T#.
- Use nearby operation comment and tool description.

Example clue:
- G100 T1 G00 A45. C0. G97 S3056 M03

---

## 4. Autodesk / Fusion Milling

Expected detection:
- Program Type: Milling
- Milling Type: 3-Axis / 4-Axis / 5-Axis depending file

Expected parser behavior:
- Use tool change as operation start.
- Operation description may appear above tool change.
- If operation name appears without new tool change, it may belong to same tool as previous operation.

Expected:
- Preserve program sequence.

---

## 5. DMG DMU Fanuc 5-Axis

Sample:
- DMG_DMU_FANUC Sample Gcode.txt

Expected detection:
- Program Type: Milling
- Milling Type: 5-Axis Milling
- Confidence: High

Expected clues:
- T# M6
- G54
- G68.2
- G53.1
- G43.4 H#
- B and C rotary axes
- Simultaneous XYZ + B/C motion

Should not detect as:
- Mill-Turn

---

## 6. DMG DMU Siemens 5-Axis MPF

Sample:
- DMG_DMU_Siemens Sample Gcode.txt

Expected detection:
- Program Type: Milling
- Milling Type: 5-Axis Milling
- Confidence: High

Expected parser output:
- Tool#: T1
- N sequence #: blank
- Operation description: OP1
- Datum: G54
- Tool Description: 0.25 TAPERED ENDMILL
- H offsets: blank
- D offsets: D1

Expected clues:
- Siemens MPF header
- CYCLE800
- TRAORI
- GROUP_BEGIN
- T="0.25 TAPERED ENDMILL"
- M6
- D1
- G54
- B/C rotary axes

Important:
- GROUP_BEGIN(,"OP1",,) = Operation description OP1.
- OP1 is not N sequence #.
- CYCLE800 parameters must never become operation comment.
- SUPA D0 must not become D offset.

---

## 7. DMG DMF Siemens 5-Axis MPF

Sample:
- DMG_DMF_SIEMENS Sample Gcode.txt

Expected detection:
- Program Type: Milling
- Milling Type: 5-Axis Milling
- Confidence: High

Expected parser output:
- Tool#: T1
- N sequence #: blank
- Operation description: OP1
- Datum: G54
- Tool Description: 0.25 TAPERED ENDMILL
- H offsets: blank
- D offsets: D1

Important:
- Same parser behavior as DMG DMU Siemens.
- GROUP_BEGIN controls operation description.
- CYCLE800 is transform/detection only, not operation comment.

---

## 8. HEIDENHAIN TNC 5-Axis

Sample:
- DMG_DMF_TNC Sample Gcode.txt

Expected detection:
- Program Type: Milling
- Milling Type: 5-Axis Milling
- Control/Profile: HEIDENHAIN TNC
- Confidence: High

Expected clues:
- BEGIN PGM
- END PGM
- TOOL CALL
- CYCL DEF
- M128
- PLANE RESET / PLANE SPATIAL
- L X+ / L B+ motion
- B/C rotary axes

Expected parser behavior:
- Tool# from TOOL CALL 1 -> T1
- Tool Description from TOOL comment
- Datum from CYCL DEF 247 / Q339
- H offsets blank
- D offsets blank unless real offset exists
- Do not use HEIDENHAIN line numbers as N sequence #

Should not detect as:
- Mill-Turn

---

## 9. Doosan 2-Axis Lathe

Sample:
- Doosan 210 2 axis testing.txt

Expected detection:
- Program Type: Lathe / Turning
- Lathe Type: 2-Axis Lathe
- Confidence: High

Expected clues:
- T0202 / T0808 / T1212 / T0303 lathe tool calls
- G97 spindle mode
- G76 threading cycle
- G28 U0 W0
- X/Z motion only
- Lathe comments such as LATHE TOOL, OD THREAD, INSERT, CENTER DRILL

Should not detect as:
- Mill-Turn

Reason:
- No Y-axis live-tool motion
- No C-axis motion
- No M6 milling tool change

---

## 10. Doosan / Mastercam Lathe Mill-Turn

Expected detection:
- Program Type: Mill-Turn
- Lathe Type: Mill-Turn / Live Tooling
- Confidence: High or Medium depending evidence

Expected clues:
- T0101 / T0202 lathe-style tool calls
- Y-axis motion
- C-axis motion
- G17/G19 plane switching
- USING Y-AXIS comments
- C-AXIS comments
- CROSS DRILL
- LEFT SPINDLE / RIGHT SPINDLE

Expected parser behavior:
- T0101 -> T1, offset 1
- T0202 -> T2, offset 2
- Use nearby comments for tool description and operation description
- Multiple datum rows may be created for repeated operation across G55/G56/G57/G58
- H offsets blank unless actual G43/G44 H exists
- D offset may use lathe offset only if no better D offset exists

---

# Regression Checklist

Before accepting parser/detection changes, verify:

- Existing 3-axis milling still detects as Milling, not Mill-Turn.
- DMG Fanuc 5-axis detects as Milling — 5-Axis Milling, High confidence.
- DMG Siemens/MPF operation comment is OP1, not CYCLE800 parameters.
- HEIDENHAIN TNC detects as Milling — 5-Axis Milling.
- Doosan 2-axis lathe detects as Lathe / Turning — 2-Axis Lathe.
- Doosan mill-turn detects as Mill-Turn only when Y/C live-tool evidence exists.
- Operation row sequence is preserved.
- No auto-sort happens unless user manually triggers sort.

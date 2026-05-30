# GcodeSetup AI Context

## Product Goal

GcodeSetup is a Streamlit web app that converts CNC G-code into an editable one-page shop-floor setup sheet.

Current beta goal:
- Support many real CNC post formats.
- Extract tool number, N sequence/block, operation description, datum, tool description, H offsets, D offsets, and remarks.
- Allow users to edit rows before printing/saving the setup sheet.
- Keep the public beta simple, professional, and safe for non-confidential testing.

## Main Rule

Do not rewrite the whole app.

Make small targeted changes only.

Do not change parser logic unless specifically requested.

Do not change UI/layout unless specifically requested.

Always preserve existing working formats.

## Current App Structure

Main files:
- app.py
- gcode_parser.py
- one_page_setup_sheet.py
- feedback_form.py
- feedback_storage.py
- setup_sheet_parser.py
- requirements.txt

## Current UI

The app includes:
- Home / Tool page
- Plans page
- About page
- Contact / Feedback page
- Upload G-code section
- Try Demo File button
- Operation rows editor
- Add Row Above / Add Row Below
- Delete rows
- Editable setup sheet header fields
- Admin-locked diagnostic section
- Feedback form

## Current Setup Sheet Layout

The setup sheet uses one combined operation table.

Do not group operation rows by datum.

Column order:
1. Tool#
2. N sequence #
3. Operation description
4. Datum
5. Tool Description
6. H offsets
7. D offsets
8. Remark

Center-align these columns in final setup sheet preview/print:
- Tool#
- N sequence #
- Datum
- H offsets
- D offsets

Left-align these columns:
- Operation description
- Tool Description
- Remark

## Parser Architecture Direction

Use a universal parser interface, but avoid overcrowding one giant parser.

Preferred structure:
- Universal detection layer
- Profile-style handlers for special formats
- Normalize all output into the same operation row fields

The app should feel universal to the user, but internally parser profiles are allowed.

## Supported / Testing Formats

Formats currently supported or being tested:
- Fanuc / Haas milling
- Basic Fanuc without N block comments
- Mastercam milling
- Autodesk / Fusion TOOLPATH format
- Brother G100 tool change
- Siemens / MPF
- DMG DMU / DMF Siemens 5-axis
- DMG DMU Fanuc 5-axis
- HEIDENHAIN TNC 5-axis
- Doosan / Mastercam lathe mill-turn
- Doosan 2-axis lathe

## Program Type Detection

Detection should return:
- program_type
- milling_type
- lathe_type
- confidence
- reasons

Program types:
- Milling
- Lathe / Turning
- Mill-Turn
- Swiss
- Unknown

Milling types:
- 3-Axis Milling
- 4-Axis Milling
- 5-Axis Milling
- Unknown Milling

Lathe types:
- 2-Axis Lathe
- Mill-Turn / Live Tooling
- Swiss
- Unknown Lathe

## 3-Axis Milling Detection

Strong clues:
- T# M6 or T#M6
- G43/G44 H offset
- G17
- G54/G55/G56 or G54P#
- G81/G83 drilling cycles
- X/Y/Z motion
- No rotary axis motion

Expected:
Milling — 3-Axis Milling

## 4-Axis Milling Detection

Strong clues:
- Normal milling clues
- One rotary axis A/B/C on actual motion lines
- No 5-axis transform code

Expected:
Milling — 4-Axis Milling

## 5-Axis Milling Detection

Strong clues:
- G43.4
- G43.5
- G68.2
- G53.1
- CYCLE800
- TRAORI
- M128
- PLANE SPATIAL
- PLANE RESET
- TCP / TCPC / RTCP
- B and C axes on motion lines
- Simultaneous XYZ + rotary motion

If these are present, confidence should be High.

Expected:
Milling — 5-Axis Milling

## 2-Axis Lathe Detection

Strong clues:
- T0202 / T0808 / T1212 style lathe tool calls
- G96 / G97
- G76 / G71 / G72 turning cycles
- G28 U0 W0
- X/Z motion only
- No Y-axis motion
- No C-axis motion
- No M6 milling tool change

Expected:
Lathe / Turning — 2-Axis Lathe

## Mill-Turn Detection

Do not classify as Mill-Turn from T0202 + G97 alone.

Mill-Turn requires lathe-style tool calls plus live-tool evidence:
- Y-axis motion
- C-axis motion
- G17/G19 live-tool sections
- USING Y-AXIS comments
- C-AXIS comments
- CROSS DRILL
- LIVE TOOL
- LEFT SPINDLE / RIGHT SPINDLE with live-tool/milling operation

Expected:
Mill-Turn

## False Positive Rules

Before checking axis motion:
- Strip comments.
- Only count Y-axis if actual Y coordinate appears on motion lines.
- Only count C-axis if actual C coordinate appears on motion lines.
- Ignore C in comments, tool names, words, paths, or file names.
- Do not classify Mill-Turn just because the word TURN appears in comments.
- Do not treat CYCLE800 parameters as operation comments.
- Do not treat HEIDENHAIN line numbers as N sequence numbers.
- Do not use C in words/comments as C-axis motion.

## Siemens / DMG MPF Rule

For DMG_DMU_SIEMENS and DMG_DMF_SIEMENS:
- CYCLE800 is only for detection / diagnostic reason.
- Never use CYCLE800 parameters as operation comment.
- GROUP_BEGIN(,"OP1",,) should become Operation description = OP1.
- OP1 should not be N sequence #.
- T="0.25 TAPERED ENDMILL" gives tool description.
- D1 after M6 gives D offset.
- G54 gives datum.
- H offset usually blank.

Expected operation row:
- Tool# = T1
- N sequence # = blank
- Operation description = OP1
- Datum = G54
- Tool Description = 0.25 TAPERED ENDMILL
- H offsets = blank
- D offsets = D1

## DMG DMU Fanuc 5-Axis Rule

Strong clues:
- T# M6
- G54
- B/C rotary axes
- G68.2
- G53.1
- G43.4 H#
- Simultaneous XYZ + B/C motion

Expected:
Milling — 5-Axis Milling
Confidence: High

## HEIDENHAIN TNC Rule

HEIDENHAIN clues:
- BEGIN PGM
- END PGM
- TOOL CALL
- CYCL DEF
- M128
- PLANE RESET / PLANE SPATIAL
- L X+ / L B+ motion

Expected:
- Milling — 5-Axis Milling
- Tool# from TOOL CALL 1
- Tool Description from TOOL comment
- Datum from CYCL DEF 247 / Q339
- H offset blank
- D offset blank unless real offset found
- Do not use line numbers as N sequence #

## Doosan 2-Axis Lathe Rule

Expected:
Lathe / Turning — 2-Axis Lathe

Tool calls:
- T0202 -> T2, offset 2
- T0808 -> T8, offset 8
- T1212 -> T12, offset 12
- T0303 -> T3, offset 3

Do not classify as Mill-Turn unless Y/C live-tool evidence exists.

## Doosan Mill-Turn Rule

Expected:
Mill-Turn

Tool calls:
- T0101 -> T1
- T0202 -> T2
- T0303 -> T3

Use nearby comments for:
- Tool Description
- Operation description

Multiple datum rows can be created if same tool repeats operation across G55/G56/G57/G58.

## Development Practice

Before changing code:
1. Identify exact file/function to change.
2. Make the smallest possible change.
3. Do not rewrite unrelated sections.
4. Preserve existing working formats.
5. After change, test at least one existing sample and the new sample.

## Current Product Strategy

Public beta is for non-confidential testing only.

Main goal now:
- Collect post-format samples.
- Improve parser coverage.
- Keep UI professional.
- Build trust with CNC programmers, machinists, manufacturing engineers, and CAM users.

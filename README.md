# CNC Setup-Sheet Verification — Free Beta v0.1

Simple Streamlit app to parse Fanuc-style G-code with deterministic regex/state logic.

**Free Beta v0.1** — Review all extracted data before shop-floor use.

**Privacy note:** Please remove confidential customer or part information before uploading. This free beta is for testing setup-sheet extraction from CNC programs.

## Features implemented

- Upload G-code file (`.nc`, `.tap`, `.txt`, `.gcode`)
- Extract:
  - Program number (`O####`)
  - Units (`G20`/`G21`)
  - Work offsets (`G54`-`G59`)
  - Tool changes (`T` + `M6`)
  - `H` offsets
  - `D` offsets
  - Spindle speed (`S`)
  - Feedrate (`F`)
  - Coolant (`M8`/`M9`)
  - Min/max `X/Y/Z` per tool
  - Comments in parentheses
- Display extracted information in clean tables

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app uses Streamlit multi-page navigation:

- **Home / Tool** — upload G-code, edit setup sheet, preview, print/save PDF
- **Plans** — Free Beta vs Pro (coming soon)
- **About** — what GcodeSetup extracts
- **Contact / Feedback** — parser feedback form

## Test files

Use sample files in `samples/`:

- `sample_part_1.nc`
- `sample_part_2.tap`

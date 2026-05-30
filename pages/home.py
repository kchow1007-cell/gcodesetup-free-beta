"""Home / Tool — main G-code setup sheet workflow."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app_shared import (
    apply_app_styles,
    build_opsheet_html_from_session,
    build_zip_bytes_from_folder,
    cnc_extensions_hint,
    decode_uploaded_cnc_bytes,
    inject_preview_chrome,
    render_beta_footer,
)
from feedback_form import render_parser_feedback_form
from gcode_parser import (
    PROGRAM_TYPE_LATHE,
    PROGRAM_TYPE_MILL_TURN,
    PROGRAM_TYPE_MILLING,
    PROGRAM_TYPE_SWISS,
    PROGRAM_TYPE_UNKNOWN,
    detect_program_type,
    format_program_type_label,
    parse_gcode,
)
from one_page_setup_sheet import (
    BETA_PRIVACY_NOTE,
    BETA_SHOP_FLOOR_WARNING,
    BETA_VERSION_LABEL,
    CLEARABLE_OPERATION_COLUMNS,
    blank_operation_row,
    clear_operation_column,
    default_metadata,
    default_operation_editor_rows,
    format_operation_row_label,
    insert_blank_row_above,
    insert_blank_row_below,
    maybe_sort_operation_rows,
    strip_editor_ui_columns,
)

apply_app_styles()

_ROOT = Path(__file__).resolve().parent.parent
_DEMO_GCODE_PATH = _ROOT / "samples" / "demo_gcode.nc"
_DEMO_ANALYSIS_KEY = "demo_gcode.nc|builtin"

_PROGRAM_TYPE_SELECT_OPTIONS = [
    "Auto Detect",
    "Milling — 3-Axis",
    "Milling — 4-Axis",
    "Milling — 5-Axis",
    "Milling — Unknown",
    "Lathe / Turning",
    "Mill-Turn",
    "Swiss",
    "Unknown",
]

_MANUAL_PROGRAM_TYPE_MAP = {
    "Milling — 3-Axis": (PROGRAM_TYPE_MILLING, "3-Axis Milling"),
    "Milling — 4-Axis": (PROGRAM_TYPE_MILLING, "4-Axis Milling"),
    "Milling — 5-Axis": (PROGRAM_TYPE_MILLING, "5-Axis Milling"),
    "Milling — Unknown": (PROGRAM_TYPE_MILLING, "Unknown Milling"),
    "Lathe / Turning": (PROGRAM_TYPE_LATHE, None),
    "Mill-Turn": (PROGRAM_TYPE_MILL_TURN, None),
    "Swiss": (PROGRAM_TYPE_SWISS, None),
    "Unknown": (PROGRAM_TYPE_UNKNOWN, None),
}


def _sync_opsheet_from_parse(result: dict, analysis_key: str, *, auto_generate: bool) -> None:
    """Initialize editable setup sheet state from a parse result (upload or demo)."""
    setup_sheet = None
    _dm = default_metadata(result, setup_sheet)
    st.session_state["opsheet_part_number"] = _dm["part_number"]
    st.session_state["opsheet_material"] = _dm["material"]
    st.session_state["opsheet_part_description"] = _dm["part_description"]
    st.session_state["opsheet_stock_size"] = _dm["stock_size"]
    st.session_state["opsheet_customer"] = _dm["customer"]
    st.session_state["opsheet_operation_num"] = _dm["operation_num"]
    st.session_state["opsheet_program_number"] = _dm["program_number"]
    st.session_state["opsheet_created_by"] = _dm["created_by"]
    st.session_state["opsheet_machine"] = _dm["machine"]
    st.session_state["opsheet_fixture"] = _dm["fixture"]
    st.session_state["opsheet_datum_lines"] = _dm["datum_lines"]
    st.session_state["opsheet_setup_notes"] = _dm["setup_notes"]
    st.session_state["opsheet_prepared_by"] = _dm["prepared_by"]
    st.session_state["opsheet_approved_by"] = _dm["approved_by"]
    st.session_state["opsheet_op_df"] = default_operation_editor_rows(result, setup_sheet)
    st.session_state["_opsheet_ak"] = analysis_key
    st.session_state.pop("_opsheet_html", None)
    st.session_state.pop("opsheet_logo_bytes", None)
    st.session_state.pop("opsheet_logo_mime", None)
    st.session_state["opsheet_delete_mode"] = False
    st.session_state["operation_rows_user_modified"] = False
    if auto_generate:
        st.session_state["shopfloor_generated"] = True


st.title("GcodeSetup — One-Page CNC Setup Sheet Generator")
st.caption(
    f"{BETA_VERSION_LABEL} — Upload your G-code to build a clean one-page "
    "shop-floor setup sheet you can edit, print, or save as PDF."
)

st.markdown(
    """
<div class="sf-card-white">
  <h3>What this tool does</h3>
  <p>GcodeSetup converts CNC G-code into a clean editable one-page shop-floor setup sheet.</p>
  <p>Upload your CNC program, review the extracted operations, edit anything needed,
     then print or save as PDF.</p>
</div>
""",
    unsafe_allow_html=True,
)

st.warning(BETA_SHOP_FLOOR_WARNING)
st.info(f"**Privacy note:** {BETA_PRIVACY_NOTE}")

_upload_col, _demo_col = st.columns([3, 1])
with _upload_col:
    uploaded_file = st.file_uploader(
        "Upload G-code file",
        help=f"Accepted: {cnc_extensions_hint()}",
    )
    st.caption(
        "Supported files: .nc, .txt, .tap, .gcode, .mpf, .min, .eia, or text-based CNC files."
    )
with _demo_col:
    st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
    if st.button("Try Demo File", use_container_width=True, key="home_try_demo_btn"):
        if not _DEMO_GCODE_PATH.is_file():
            st.error("Demo file is missing. Expected samples/demo_gcode.nc.")
        else:
            st.session_state["home_demo_active"] = True
            st.session_state["home_demo_bytes"] = _DEMO_GCODE_PATH.read_bytes()
            st.session_state.pop("_opsheet_ak", None)
            st.rerun()

demo_active = bool(st.session_state.get("home_demo_active")) and st.session_state.get("home_demo_bytes")
if uploaded_file is not None:
    st.session_state.pop("home_demo_active", None)
    st.session_state.pop("home_demo_bytes", None)
    program_bytes = uploaded_file.getvalue()
    analysis_key = "|".join([uploaded_file.name, str(uploaded_file.size)])
    program_label = uploaded_file.name
elif demo_active:
    program_bytes = st.session_state["home_demo_bytes"]
    analysis_key = _DEMO_ANALYSIS_KEY
    program_label = "demo_gcode.nc"
    st.caption(
        "Demo file loaded. This is a fake sample program for testing the workflow."
    )
else:
    st.info("Upload a G-code file or click **Try Demo File** to begin.")
    render_beta_footer()
    st.stop()

raw_text, decode_err = decode_uploaded_cnc_bytes(program_bytes)
if decode_err:
    st.error(decode_err)
    render_beta_footer()
    st.stop()

result = parse_gcode(raw_text)
st.session_state["gcode_parse_result"] = result
setup_sheet = None

if st.session_state.get("_program_type_ak") != analysis_key:
    st.session_state["program_type_detection"] = detect_program_type(raw_text)
    st.session_state["_program_type_ak"] = analysis_key

_program_type_choice = st.selectbox(
    "Program Type",
    options=_PROGRAM_TYPE_SELECT_OPTIONS,
    index=0,
    key="program_type_select",
    help="Auto Detect uses clues in the G-code. Choose a type manually to override.",
)

_detection = st.session_state.get("program_type_detection") or detect_program_type(raw_text)
if _program_type_choice == "Auto Detect":
    _program_type = _detection["program_type"]
    _milling_type = _detection.get("milling_type")
    _lathe_type = _detection.get("lathe_type")
    _display_label = format_program_type_label(
        _program_type, _milling_type, _lathe_type
    )
    _display_confidence = _detection["confidence"]
    _display_reasons = _detection.get("reasons") or []
    _type_source = "auto"
elif _program_type_choice in _MANUAL_PROGRAM_TYPE_MAP:
    _program_type, _milling_type = _MANUAL_PROGRAM_TYPE_MAP[_program_type_choice]
    _display_label = format_program_type_label(_program_type, _milling_type)
    _display_confidence = "—"
    _display_reasons = [f"Manually selected: {_program_type_choice}"]
    _type_source = "manual"
else:
    _program_type = _program_type_choice
    _milling_type = None
    _display_label = _program_type
    _display_confidence = "—"
    _display_reasons = [f"Manually selected: {_program_type_choice}"]
    _type_source = "manual"

st.session_state["program_type_effective"] = _display_label
st.session_state["program_type_base"] = _program_type
st.session_state["milling_type_effective"] = _milling_type

_reason_lines = "\n".join(f"- {r}" for r in _display_reasons[:8]) if _display_reasons else "- No clues recorded"
_conf_line = (
    f"**Confidence:** {_display_confidence}"
    if _type_source == "auto"
    else "**Confidence:** — (manual selection)"
)
st.markdown(
    f"""
<div class="sf-card-white" style="margin-bottom:1rem;">
  <h3 style="margin-top:0;">Detected program type</h3>
  <p style="margin:0 0 0.35rem 0;font-size:1.05rem;"><strong>{_display_label}</strong></p>
  <p style="margin:0 0 0.5rem 0;">{_conf_line}</p>
  <p style="margin:0;font-size:0.92rem;color:#444;"><strong>Reasons:</strong><br/>{_reason_lines}</p>
</div>
""",
    unsafe_allow_html=True,
)

_opsheet_ak = analysis_key
if st.session_state.get("_opsheet_ak") != _opsheet_ak:
    _sync_opsheet_from_parse(
        result,
        _opsheet_ak,
        auto_generate=demo_active and uploaded_file is None,
    )
elif demo_active and uploaded_file is None and not st.session_state.get("shopfloor_generated"):
    st.session_state["shopfloor_generated"] = True

if "shopfloor_generated" not in st.session_state:
    st.session_state["shopfloor_generated"] = False
if "opsheet_delete_mode" not in st.session_state:
    st.session_state["opsheet_delete_mode"] = False
if "operation_rows_user_modified" not in st.session_state:
    st.session_state["operation_rows_user_modified"] = False

if "opsheet_op_df" not in st.session_state:
    st.session_state["opsheet_op_df"] = default_operation_editor_rows(result, setup_sheet)
if "opsheet_part_number" not in st.session_state:
    _fd = default_metadata(result, setup_sheet)
    st.session_state["opsheet_part_number"] = _fd["part_number"]
    st.session_state["opsheet_material"] = _fd["material"]
    st.session_state["opsheet_part_description"] = _fd["part_description"]
    st.session_state["opsheet_stock_size"] = _fd["stock_size"]
    st.session_state["opsheet_customer"] = _fd["customer"]
    st.session_state["opsheet_operation_num"] = _fd["operation_num"]
    st.session_state["opsheet_program_number"] = _fd["program_number"]
    st.session_state["opsheet_created_by"] = _fd.get("created_by", "")
    st.session_state["opsheet_machine"] = _fd["machine"]
    st.session_state["opsheet_fixture"] = _fd.get("fixture", "")
    st.session_state["opsheet_datum_lines"] = _fd["datum_lines"]
    st.session_state["opsheet_setup_notes"] = _fd["setup_notes"]
    st.session_state["opsheet_prepared_by"] = _fd["prepared_by"]
    st.session_state["opsheet_approved_by"] = _fd["approved_by"]
if "opsheet_created_by" not in st.session_state:
    st.session_state["opsheet_created_by"] = ""
if "opsheet_fixture" not in st.session_state:
    st.session_state["opsheet_fixture"] = ""

if st.button("Generate Setup Sheet", type="primary", key="opsheet_generate_btn"):
    st.session_state["shopfloor_generated"] = True

gen_bottom = False

if st.session_state.get("shopfloor_generated"):
    st.divider()
    st.subheader("Edit your setup sheet")
    st.caption(
        "Fill in or adjust the fields below, then click **Generate Setup Sheet** "
        "to refresh the preview."
    )

    logo_up = st.file_uploader(
        "Company logo (optional)",
        type=["png", "jpg", "jpeg", "gif", "webp"],
        key="opsheet_logo_uploader",
    )
    if logo_up is not None:
        st.session_state["opsheet_logo_bytes"] = logo_up.getvalue()
        st.session_state["opsheet_logo_mime"] = logo_up.type or "image/png"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Header**")
    with c2:
        st.caption("Logo appears on the sheet when uploaded above.")

    _r1a, _r1b = st.columns(2)
    with _r1a:
        st.text_input("PART#", key="opsheet_part_number")
    with _r1b:
        st.text_input("PART DESCRIPTION", key="opsheet_part_description")
    _r2a, _r2b = st.columns(2)
    with _r2a:
        st.text_input("CUSTOMER", key="opsheet_customer")
    with _r2b:
        st.text_input("MATERIAL", key="opsheet_material")
    _r3a, _r3b = st.columns(2)
    with _r3a:
        st.text_input("OPERATION#", key="opsheet_operation_num")
    with _r3b:
        st.text_input("STOCK SIZE", key="opsheet_stock_size")
    _r4a, _r4b = st.columns(2)
    with _r4a:
        st.text_input(
            "PROGRAM#",
            key="opsheet_program_number",
            help="Prefilled from G-code O#### when available; you can edit anytime.",
        )
    with _r4b:
        st.text_input("CREATED BY", key="opsheet_created_by")

    _mf_left, _mf_datum = st.columns(2)
    with _mf_left:
        _m1, _m2 = st.columns(2)
        with _m1:
            st.text_input("MACHINE", key="opsheet_machine")
        with _m2:
            st.text_input("FIXTURE", key="opsheet_fixture")
    with _mf_datum:
        st.text_area(
            "DATUM",
            key="opsheet_datum_lines",
            height=100,
            help="Work offsets — one per line (e.g. G54:). Prefilled from G-code when detected.",
        )

    st.text_area("SETUP NOTES", key="opsheet_setup_notes", height=140)

    st.markdown("**Operation rows**")
    st.info(
        "Edit operation rows below. Use **Add Row Above** or **Add Row Below** to insert manual operations. "
        "Use **Delete Rows** to remove selected rows. Empty rows will not appear in the final setup sheet."
    )

    _confirm_delete = False
    _cancel_delete = False

    _user_modified = st.session_state.get("operation_rows_user_modified", False)
    _op_df = maybe_sort_operation_rows(
        strip_editor_ui_columns(st.session_state["opsheet_op_df"]),
        _user_modified,
    )
    _delete_mode = st.session_state.get("opsheet_delete_mode", False)
    _fillna_cols = [
        "Remark", "Tool#", "Block#", "Operation Comment", "Tool Description",
        "H offsets", "D offsets", "Datum",
    ]

    _del_row_a1, _ = st.columns([1, 5])
    with _del_row_a1:
        if not _delete_mode and st.button("Delete Rows", key="opsheet_delete_rows_btn"):
            st.session_state["opsheet_delete_mode"] = True
            st.session_state.pop("opsheet_op_editor", None)
            _delete_mode = True

    if _op_df.empty:
        if st.button("+ Add Row", key="opsheet_add_first_row_btn"):
            st.session_state["opsheet_op_df"] = pd.DataFrame([blank_operation_row("G54")])
            st.session_state["operation_rows_user_modified"] = True
            _op_df = st.session_state["opsheet_op_df"]
    else:
        _row_positions = list(range(len(_op_df)))
        _row_labels = [format_operation_row_label(i, _op_df.iloc[i]) for i in _row_positions]
        _add_col1, _add_col2, _add_col3 = st.columns(
            [4, 1.35, 1.35],
            vertical_alignment="bottom",
        )
        with _add_col1:
            _add_row_pos = st.selectbox(
                "Add row above or below",
                _row_positions,
                format_func=lambda i: _row_labels[i],
                key="opsheet_add_row_select",
            )
        with _add_col2:
            if st.button("+ Add Row Above", use_container_width=True, key="opsheet_add_above_btn"):
                st.session_state["opsheet_op_df"] = insert_blank_row_above(_op_df, int(_add_row_pos))
                st.session_state["operation_rows_user_modified"] = True
                st.session_state.pop("opsheet_op_editor", None)
                _op_df = st.session_state["opsheet_op_df"]
                _user_modified = True
        with _add_col3:
            if st.button("+ Add Row Below", use_container_width=True, key="opsheet_add_below_btn"):
                st.session_state["opsheet_op_df"] = insert_blank_row_below(_op_df, int(_add_row_pos))
                st.session_state["operation_rows_user_modified"] = True
                st.session_state.pop("opsheet_op_editor", None)
                _op_df = st.session_state["opsheet_op_df"]
                _user_modified = True

    if _delete_mode:
        st.markdown("**Delete mode** — tick **Delete?** on rows to remove, then confirm or cancel.")

    st.markdown("**Column Tools**")
    _col_clear_1, _col_clear_2, _col_clear_3, _ = st.columns([3, 2.2, 1.6, 2])
    with _col_clear_1:
        _clear_column_name = st.selectbox(
            "Select column to clear",
            options=list(CLEARABLE_OPERATION_COLUMNS),
            key="opsheet_clear_column_select",
        )
    with _col_clear_2:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        _clear_column_confirmed = st.checkbox(
            "I understand this will clear the selected column.",
            key="opsheet_clear_column_confirm",
        )
    with _col_clear_3:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        _clear_column_clicked = st.button(
            "Clear Selected Column",
            key="opsheet_clear_column_btn",
            disabled=not _clear_column_confirmed or _op_df.empty,
            use_container_width=True,
        )
    _column_clear_applied = False
    if _clear_column_clicked and _clear_column_confirmed and not _op_df.empty:
        st.session_state["opsheet_op_df"] = (
            clear_operation_column(_op_df, _clear_column_name)
            .fillna({c: "" for c in _fillna_cols})
            .reset_index(drop=True)
        )
        st.session_state["operation_rows_user_modified"] = True
        st.session_state.pop("opsheet_op_editor", None)
        _op_df = maybe_sort_operation_rows(
            strip_editor_ui_columns(st.session_state["opsheet_op_df"]),
            True,
        )
        _column_clear_applied = True

    _editor_df = maybe_sort_operation_rows(strip_editor_ui_columns(_op_df.copy()), _user_modified)
    if _delete_mode:
        if "Delete?" not in _editor_df.columns:
            _editor_df.insert(0, "Delete?", False)

    _col_config = {
        "Remark": st.column_config.TextColumn("Remark", width="medium"),
        "Datum": st.column_config.TextColumn("Datum", width="small"),
        "Tool#": st.column_config.TextColumn("Tool#", width="small"),
        "Block#": st.column_config.TextColumn("Block#", width="small"),
    }
    if _delete_mode:
        _col_config["Delete?"] = st.column_config.CheckboxColumn("Delete?", default=False)

    _edited_ops = st.data_editor(
        _editor_df,
        key="opsheet_op_editor",
        num_rows="fixed",
        use_container_width=True,
        column_config=_col_config,
    )

    if _delete_mode:
        _confirm_col, _cancel_col = st.columns(2)
        with _confirm_col:
            _confirm_delete = st.button(
                "Confirm Delete Checked Rows",
                type="primary",
                use_container_width=True,
                key="opsheet_confirm_delete_btn",
            )
        with _cancel_col:
            _cancel_delete = st.button(
                "Cancel Delete",
                use_container_width=True,
                key="opsheet_cancel_delete_btn",
            )
        if _cancel_delete:
            st.session_state["opsheet_delete_mode"] = False
            st.session_state.pop("opsheet_op_editor", None)
            _delete_mode = False

    _skip_persist = False
    if _delete_mode and _confirm_delete:
        if "Delete?" in _edited_ops.columns:
            _marked = _edited_ops["Delete?"].fillna(False).astype(bool)
            if _marked.any():
                _kept = _edited_ops.loc[~_marked]
                st.session_state["opsheet_op_df"] = (
                    strip_editor_ui_columns(_kept).fillna({c: "" for c in _fillna_cols}).reset_index(drop=True)
                )
                st.session_state["operation_rows_user_modified"] = True
                st.session_state["opsheet_delete_mode"] = False
                st.session_state.pop("opsheet_op_editor", None)
                _skip_persist = True
            else:
                st.warning("Tick **Delete?** on one or more rows, then click **Confirm Delete Checked Rows**.")
        else:
            st.session_state["opsheet_delete_mode"] = False

    if not _skip_persist and not _column_clear_applied:
        st.session_state["opsheet_op_df"] = (
            strip_editor_ui_columns(_edited_ops).fillna({c: "" for c in _fillna_cols}).reset_index(drop=True)
        )
        st.session_state["operation_rows_user_modified"] = True

    pb1, pb2 = st.columns(2)
    with pb1:
        st.text_input("PREPARED BY", key="opsheet_prepared_by")
    with pb2:
        st.text_input("APPROVED BY", key="opsheet_approved_by")

    st.session_state["_opsheet_html"] = build_opsheet_html_from_session()

    st.divider()
    st.markdown(
        "**To save as PDF:** use your browser Print button and choose **Save as PDF**."
    )
    st.caption(
        "You can also use **Print Setup Sheet** in the preview below; "
        "then choose Save as PDF in the print dialog."
    )

    dl_col, _ = st.columns([1, 3])
    with dl_col:
        _html_bytes = (
            st.session_state["_opsheet_html"].encode("utf-8")
            if st.session_state.get("_opsheet_html")
            else b""
        )
        st.download_button(
            label="Download HTML Setup Sheet",
            data=_html_bytes or b"<!-- Click Generate Setup Sheet first -->",
            file_name="shop_floor_setup_sheet.html",
            mime="text/html",
            key="opsheet_download_html",
            disabled=not bool(st.session_state.get("_opsheet_html")),
        )

    gen_bottom = st.button("Generate Setup Sheet", type="primary", key="opsheet_generate_btn_bottom")

    if st.session_state.get("_opsheet_html"):
        st.markdown("##### One-page preview")
        st.markdown(
            """
<style>
div[data-testid="stHtml"] { background-color: #ffffff !important; }
div[data-testid="stHtml"] iframe { background-color: #ffffff !important; }
</style>
""",
            unsafe_allow_html=True,
        )
        components.html(
            inject_preview_chrome(st.session_state["_opsheet_html"]),
            height=980,
            scrolling=True,
        )
    else:
        st.info("Click **Generate Setup Sheet** to create the preview.")

else:
    st.info("Click **Generate Setup Sheet** when you are ready to review and print your one-page sheet.")

render_parser_feedback_form()

if "admin_unlocked" not in st.session_state:
    st.session_state["admin_unlocked"] = False


def _render_admin_diagnostics(parse_result: dict) -> None:
    st.subheader("Program Summary")
    st.table(pd.DataFrame([parse_result["summary"]]))

    st.subheader("Tool / Offset / Speed / Feed / Travel")
    tool_rows = parse_result["tool_rows"]
    if tool_rows:
        st.dataframe(pd.DataFrame(tool_rows), use_container_width=True)
    else:
        st.warning("No tool-related data found.")

    st.subheader("Program Header")
    program_header = parse_result.get("program_header", {})
    if program_header:
        st.dataframe(pd.DataFrame([program_header]), use_container_width=True)
    else:
        st.write("No program header fields found.")

    st.subheader("Tool List From G-code")
    header_tool_rows = parse_result.get("header_tool_table", [])
    if header_tool_rows:
        st.dataframe(pd.DataFrame(header_tool_rows), use_container_width=True)
    else:
        st.write("No header tool list found.")

    st.subheader("Operation Blocks by N Number")
    operation_blocks = parse_result.get("operation_blocks", [])
    if operation_blocks:
        operation_df = pd.DataFrame(operation_blocks)
        operation_df = operation_df.rename(
            columns={
                "block_number": "Block",
                "tool_number": "Tool",
                "tool_comment": "Tool Comment",
                "operation_comment": "Operation Comment",
                "tool_description_from_header": "Tool Description (Header)",
                "h_offset": "H Offset",
                "h_offset_from_header": "H Offset (Header)",
                "d_offset_used": "D Offset Used",
                "d_offset_from_header": "D Offset (Header)",
                "spindle_speed": "Spindle",
                "feedrates": "Feedrates",
                "work_offsets": "Work Offsets",
                "coolant": "Coolant",
                "canned_cycles": "Cycles",
                "min_z": "Min Z",
                "max_z": "Max Z",
            }
        )
        desired_columns = [
            "Block", "Tool", "Tool Comment", "Operation Comment",
            "Tool Description (Header)", "H Offset", "H Offset (Header)",
            "D Offset Used", "D Offset (Header)", "Spindle", "Feedrates",
            "Work Offsets", "Coolant", "Cycles", "Min Z", "Max Z",
        ]
        operation_df = operation_df[desired_columns]
        st.dataframe(operation_df, use_container_width=True)
    else:
        st.write("No operation blocks found.")

    st.subheader("Comments (Parentheses)")
    if parse_result["comments"]:
        comments_df = pd.DataFrame({"Comment": parse_result["comments"]})
        st.dataframe(comments_df, use_container_width=True)
    else:
        st.write("No comments found.")

    st.subheader("Admin — Feedback Downloads")
    feedback_root = Path(__file__).resolve().parent.parent / "feedback"
    feedback_csv = feedback_root / "feedback_log.csv"
    feedback_uploads = feedback_root / "uploads"
    feedback_snippets = feedback_root / "snippets"

    has_csv = feedback_csv.exists() and feedback_csv.is_file() and feedback_csv.stat().st_size > 0
    uploads_zip = build_zip_bytes_from_folder(feedback_uploads)
    snippets_zip = build_zip_bytes_from_folder(feedback_snippets)

    if not has_csv and not uploads_zip and not snippets_zip:
        st.caption("No feedback collected yet.")
    else:
        if has_csv:
            st.download_button(
                label="Download feedback_log.csv",
                data=feedback_csv.read_bytes(),
                file_name="feedback_log.csv",
                mime="text/csv",
                key="admin_download_feedback_csv",
            )
        if uploads_zip:
            st.download_button(
                label="Download all uploaded feedback files as ZIP",
                data=uploads_zip,
                file_name="feedback_uploads.zip",
                mime="application/zip",
                key="admin_download_feedback_uploads_zip",
            )
        if snippets_zip:
            st.download_button(
                label="Download all pasted snippets as ZIP",
                data=snippets_zip,
                file_name="feedback_snippets.zip",
                mime="application/zip",
                key="admin_download_feedback_snippets_zip",
            )


st.divider()
with st.expander("Advanced / Diagnostic Data", expanded=False):
    admin_password = st.secrets.get("ADMIN_PASSWORD")
    if not admin_password:
        st.warning("Admin password is not configured.")
    elif st.session_state.get("admin_unlocked"):
        _lock_col, _ = st.columns([1, 4])
        with _lock_col:
            if st.button("Lock Admin Panel", key="admin_lock_panel_btn"):
                st.session_state["admin_unlocked"] = False
                st.rerun()
        _parse_result = st.session_state.get("gcode_parse_result")
        if _parse_result:
            _render_admin_diagnostics(_parse_result)
        else:
            st.caption("Upload a G-code file on this page to view parser diagnostics.")
    else:
        entered_password = st.text_input(
            "Enter admin password",
            type="password",
            key="admin_password_input",
        )
        if st.button("Unlock", key="admin_unlock_btn"):
            if entered_password == str(admin_password):
                st.session_state["admin_unlocked"] = True
                st.rerun()
            else:
                st.error("Incorrect password")

render_beta_footer()

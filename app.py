import base64
import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from gcode_parser import parse_gcode
from one_page_setup_sheet import (
    BETA_FOOTER_TEXT,
    BETA_PRIVACY_NOTE,
    BETA_SHOP_FLOOR_WARNING,
    BETA_VERSION_LABEL,
    CLEARABLE_OPERATION_COLUMNS,
    blank_operation_row,
    build_one_page_html,
    clear_operation_column,
    default_metadata,
    default_operation_editor_rows,
    format_operation_row_label,
    insert_blank_row_below,
    maybe_sort_operation_rows,
    strip_editor_ui_columns,
)
from feedback_form import render_parser_feedback_form

_CNC_TEXT_ERROR = "This file could not be read as a text-based CNC program."

# Common CNC program extensions (also accepts files with no extension).
_CNC_EXTENSIONS_HINT = "nc, tap, txt, gcode, min, eia, mpf, h, cnc, or no extension"


def _is_plausible_cnc_text(data: bytes, text: str) -> bool:
    """Reject obvious binary content; accept typical ASCII/ANSI CNC programs."""
    if b"\x00" in data:
        return False
    sample = text[:8000]
    if not sample.strip():
        return False
    printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\r\t")
    return printable / len(sample) >= 0.85


def decode_uploaded_cnc_bytes(data: bytes) -> tuple[str | None, str | None]:
    """Decode uploaded bytes as text: utf-8, then cp1252, then latin-1."""
    if not data:
        return None, _CNC_TEXT_ERROR
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            if _is_plausible_cnc_text(data, text):
                return text, None
        except UnicodeDecodeError:
            continue
    return None, _CNC_TEXT_ERROR


def _inject_preview_chrome(html_doc: str) -> str:
    """
    Wrap the one-page document in a white preview canvas with print-friendly CSS
    and a Print button that runs window.print() in this iframe.
    """
    style_inj = """<style type="text/css">
@media print {
  @page { size: letter portrait; margin: 0.25in; }
  html, body { margin: 0; background: #fff !important; padding: 0 !important;
    -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .no-print, .sf-no-print { display: none !important; }
  .sf-page-outer, .setup-sheet-page {
    width: 100%; max-width: none; box-shadow: none; border: none; padding: 0;
  }
  .setup-sheet-page td,
  .setup-sheet-page th {
    overflow: visible !important;
    white-space: normal !important;
    word-break: break-word !important;
  }
  .datum-value,
  .setup-notes-value,
  .machine-fixture-datum-value {
    height: auto !important;
    min-height: auto;
    overflow: visible !important;
    white-space: pre-line !important;
  }
  .operation-section { break-inside: auto; page-break-inside: auto; }
  .operation-section:first-of-type { margin-top: 6px; page-break-before: auto; break-before: auto; }
  .operation-table { break-inside: auto; page-break-inside: auto; }
  .operation-section-title { break-after: avoid; page-break-after: avoid; }
  .operation-table thead { display: table-header-group; }
  tr { break-inside: avoid; page-break-inside: avoid; }
  .op-sheet-table td {
    height: auto !important;
    overflow: visible !important;
    white-space: normal !important;
  }
  .logo-cell {
    width: 150px !important; min-width: 150px !important; max-width: 150px !important;
    height: 85px !important;
  }
  .logo-box {
    width: 100% !important; height: 100% !important; overflow: hidden !important;
  }
  .logo-text-screen { display: none !important; }
  .logo-text-print { display: inline !important; }
}
html, body, .preview-wrapper {
  background: #ffffff !important;
}
body.sf-outer-body {
  margin: 0 !important;
  padding: 14px 12px 24px !important;
  min-height: 100vh;
  box-sizing: border-box;
  font-family: system-ui, Segoe UI, sans-serif;
}
.preview-wrapper {
  background: #ffffff;
}
.sf-toolbar { text-align: center; margin-bottom: 12px; background: #ffffff; }
.sf-toolbar button {
  padding: 0.45rem 1rem;
  font-size: 0.875rem;
  cursor: pointer;
  border-radius: 0.25rem;
  border: 1px solid rgba(49,51,63,0.2);
  background: #fff;
  font-weight: 500;
}
.sf-page-outer {
  max-width: 8.5in;
  margin: 0 auto;
  background: #ffffff !important;
  border: none;
  box-shadow: none;
  padding: 10px 8px;
  box-sizing: border-box;
  font-family: Arial, Helvetica, sans-serif;
  color: #000;
}
.setup-sheet-page {
  background: #ffffff !important;
  box-shadow: none;
}
</style>"""
    if "</head>" in html_doc:
        html_doc = html_doc.replace("</head>", style_inj + "</head>", 1)

    def _open_body(_m: re.Match) -> str:
        return (
            '<body class="sf-outer-body preview-wrapper" style="margin:0;padding:14px 12px 24px;'
            'background:#ffffff;font-family:system-ui,Segoe UI,sans-serif;">'
            '<div class="sf-toolbar sf-no-print">'
            '<button type="button" onclick="window.print()">Print Setup Sheet</button>'
            "</div>"
            '<div class="sf-page-outer setup-sheet-page">'
        )

    doc_new, n = re.subn(r"<body[^>]*>", _open_body, html_doc, count=1)
    if n != 1:
        return html_doc
    doc_new = re.sub(
        r"</body>\s*</html>\s*$",
        "</div></body></html>",
        doc_new,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return doc_new


def _session_text(key: str) -> str:
    """Editable field value for preview — never fall back to parser output."""
    v = st.session_state.get(key)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s == "-" else s


def _build_opsheet_html_from_session() -> str:
    _meta = {
        "part_number": _session_text("opsheet_part_number"),
        "material": _session_text("opsheet_material"),
        "part_description": _session_text("opsheet_part_description"),
        "stock_size": _session_text("opsheet_stock_size"),
        "customer": _session_text("opsheet_customer"),
        "operation_num": _session_text("opsheet_operation_num"),
        "program_number": _session_text("opsheet_program_number"),
        "created_by": _session_text("opsheet_created_by"),
        "machine": _session_text("opsheet_machine"),
        "fixture": _session_text("opsheet_fixture"),
        "datum_lines": _session_text("opsheet_datum_lines"),
        "setup_notes": _session_text("opsheet_setup_notes"),
        "prepared_by": _session_text("opsheet_prepared_by"),
        "approved_by": _session_text("opsheet_approved_by"),
    }
    _logo_b64 = None
    _logo_mime = None
    _lb = st.session_state.get("opsheet_logo_bytes")
    _lm_raw = (st.session_state.get("opsheet_logo_mime") or "").split(";")[0].strip().lower()
    _allowed_logo = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
    if _lb:
        _logo_b64 = base64.b64encode(_lb).decode("ascii")
        _logo_mime = _lm_raw if _lm_raw in _allowed_logo else "image/png"

    return build_one_page_html(
        _meta,
        st.session_state["opsheet_op_df"],
        logo_b64=_logo_b64,
        logo_mime=_logo_mime,
        preserve_operation_order=True,
    )


def _render_beta_footer() -> None:
    st.markdown("---")
    st.caption(BETA_FOOTER_TEXT)


def _build_zip_bytes_from_folder(folder: Path) -> bytes | None:
    if not folder.exists() or not folder.is_dir():
        return None
    files = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    if not files:
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            zf.write(file_path, arcname=str(file_path.relative_to(folder)))
    return buffer.getvalue()


st.set_page_config(
    page_title=f"Shop Floor — One-Page Setup Sheet ({BETA_VERSION_LABEL})",
    layout="wide",
)
st.title("Shop Floor — One-Page Setup Sheet")
st.caption(
    f"{BETA_VERSION_LABEL} — Upload your G-code to create a clean one-page "
    "shop-floor setup sheet."
)
st.warning(BETA_SHOP_FLOOR_WARNING)
st.info(f"**Privacy note:** {BETA_PRIVACY_NOTE}")

uploaded_file = st.file_uploader(
    "Upload G-code file",
    help=f"Accepted: {_CNC_EXTENSIONS_HINT}",
)
st.caption(
    "Supported files: .nc, .txt, .tap, .gcode, .mpf, .min, .eia, or text-based CNC files."
)

if uploaded_file is None:
    st.info("Upload a G-code file to begin.")
    _render_beta_footer()
    st.stop()

raw_text, _decode_err = decode_uploaded_cnc_bytes(uploaded_file.getvalue())
if _decode_err:
    st.error(_decode_err)
    _render_beta_footer()
    st.stop()

result = parse_gcode(raw_text)
# Free Beta v0.1: G-code only — setup sheet PDF upload is disabled in the UI.
setup_sheet = None


def _opsheet_analysis_key():
    return "|".join([uploaded_file.name, str(uploaded_file.size)])


_opsheet_ak = _opsheet_analysis_key()
if st.session_state.get("_opsheet_ak") != _opsheet_ak:
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
    st.session_state["_opsheet_ak"] = _opsheet_ak
    st.session_state.pop("_opsheet_html", None)
    st.session_state.pop("opsheet_logo_bytes", None)
    st.session_state.pop("opsheet_logo_mime", None)
    st.session_state["shopfloor_generated"] = False
    st.session_state["opsheet_delete_mode"] = False
    st.session_state["operation_rows_user_modified"] = False

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

gen_top = st.button("Generate Setup Sheet", type="primary", key="opsheet_generate_btn")
if gen_top:
    st.session_state["shopfloor_generated"] = True

gen_bottom = False

if st.session_state.get("shopfloor_generated"):
    st.divider()
    st.subheader("Edit your setup sheet")
    st.caption("Fill in or adjust the fields below, then click **Generate Setup Sheet** to refresh the preview.")

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
        "Edit operation rows below. Use **Add Row Below** to insert manual operations. "
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

    _del_row_a1, _del_row_a2 = st.columns([1, 5])
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
        _add_col1, _add_col2, _add_col3 = st.columns([4, 1.2, 3])
        with _add_col1:
            _add_below_pos = st.selectbox(
                "Add row below",
                _row_positions,
                format_func=lambda i: _row_labels[i],
                key="opsheet_add_below_select",
            )
        with _add_col2:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            if st.button("+ Add Row Below", use_container_width=True, key="opsheet_add_below_btn"):
                st.session_state["opsheet_op_df"] = insert_blank_row_below(_op_df, int(_add_below_pos))
                st.session_state["operation_rows_user_modified"] = True
                st.session_state.pop("opsheet_op_editor", None)
                _op_df = st.session_state["opsheet_op_df"]
                _user_modified = True
        with _add_col3:
            pass

    if _delete_mode:
        st.markdown("**Delete mode** — tick **Delete?** on rows to remove, then confirm or cancel.")

    st.markdown("**Column Tools**")
    _col_clear_1, _col_clear_2, _col_clear_3, _col_clear_4 = st.columns([3, 2.2, 1.6, 2])
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
    with _col_clear_4:
        pass
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

    st.session_state["_opsheet_html"] = _build_opsheet_html_from_session()

    st.divider()
    st.markdown(
        "**To save as PDF:** use your browser Print button and choose **Save as PDF**."
    )
    st.caption(
        "You can also use **Print Setup Sheet** in the preview below; then choose Save as PDF in the print dialog."
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
div[data-testid="stHtml"] {
  background-color: #ffffff !important;
}
div[data-testid="stHtml"] iframe {
  background-color: #ffffff !important;
}
</style>
""",
            unsafe_allow_html=True,
        )
        components.html(
            _inject_preview_chrome(st.session_state["_opsheet_html"]),
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


def _render_admin_diagnostics() -> None:
    st.subheader("Program Summary")
    summary_df = pd.DataFrame([result["summary"]])
    st.table(summary_df)

    st.subheader("Tool / Offset / Speed / Feed / Travel")
    tool_rows = result["tool_rows"]
    if tool_rows:
        st.dataframe(pd.DataFrame(tool_rows), use_container_width=True)
    else:
        st.warning("No tool-related data found.")

    st.subheader("Program Header")
    program_header = result.get("program_header", {})
    if program_header:
        st.dataframe(pd.DataFrame([program_header]), use_container_width=True)
    else:
        st.write("No program header fields found.")

    st.subheader("Tool List From G-code")
    header_tool_rows = result.get("header_tool_table", [])
    if header_tool_rows:
        st.dataframe(pd.DataFrame(header_tool_rows), use_container_width=True)
    else:
        st.write("No header tool list found.")

    st.subheader("Operation Blocks by N Number")
    operation_blocks = result.get("operation_blocks", [])
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
            "Block",
            "Tool",
            "Tool Comment",
            "Operation Comment",
            "Tool Description (Header)",
            "H Offset",
            "H Offset (Header)",
            "D Offset Used",
            "D Offset (Header)",
            "Spindle",
            "Feedrates",
            "Work Offsets",
            "Coolant",
            "Cycles",
            "Min Z",
            "Max Z",
        ]
        operation_df = operation_df[desired_columns]
        st.dataframe(operation_df, use_container_width=True)
    else:
        st.write("No operation blocks found.")

    st.subheader("Comments (Parentheses)")
    if result["comments"]:
        comments_df = pd.DataFrame({"Comment": result["comments"]})
        st.dataframe(comments_df, use_container_width=True)
    else:
        st.write("No comments found.")

    st.subheader("Admin — Feedback Downloads")
    feedback_root = Path(__file__).resolve().parent / "feedback"
    feedback_csv = feedback_root / "feedback_log.csv"
    feedback_uploads = feedback_root / "uploads"
    feedback_snippets = feedback_root / "snippets"

    has_csv = feedback_csv.exists() and feedback_csv.is_file() and feedback_csv.stat().st_size > 0
    uploads_zip = _build_zip_bytes_from_folder(feedback_uploads)
    snippets_zip = _build_zip_bytes_from_folder(feedback_snippets)

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
        _render_admin_diagnostics()
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

st.markdown("---")
_render_beta_footer()

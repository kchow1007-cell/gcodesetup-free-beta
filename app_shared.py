"""
Shared helpers and styling for the GcodeSetup Streamlit multi-page app.
"""
from __future__ import annotations

import base64
import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from one_page_setup_sheet import BETA_FOOTER_TEXT, build_one_page_html

_CNC_TEXT_ERROR = "This file could not be read as a text-based CNC program."
_CNC_EXTENSIONS_HINT = "nc, tap, txt, gcode, min, eia, mpf, h, cnc, or no extension"


def apply_app_styles() -> None:
    """Clean white layout and simple section cards for marketing pages."""
    st.markdown(
        """
<style>
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background-color: #ffffff;
}
[data-testid="stSidebar"] {
  background-color: #f8f9fa;
}
.sf-page-intro {
  color: #444;
  font-size: 1.05rem;
  line-height: 1.5;
  margin-bottom: 1.25rem;
}
.sf-card {
  background: #fafafa;
  border: 1px solid #e3e3e3;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}
.sf-card-white {
  background: #ffffff;
  border: 1px solid #e3e3e3;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}
.sf-card-white h3 {
  margin-top: 0;
  margin-bottom: 0.5rem;
  font-size: 1.1rem;
  color: #111;
}
.sf-card-white p {
  margin: 0 0 0.5rem 0;
  line-height: 1.5;
  color: #333;
}
.sf-card-white p:last-child { margin-bottom: 0; }
.sf-card h3 {
  margin-top: 0;
  margin-bottom: 0.5rem;
  font-size: 1.1rem;
  color: #111;
}
.sf-card ul {
  margin: 0.4rem 0 0 1.1rem;
  padding: 0;
  line-height: 1.45;
}
.sf-card li { margin-bottom: 0.25rem; }
.sf-note {
  background: #fff8e6;
  border: 1px solid #f0d78c;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-size: 0.92rem;
  color: #5c4a00;
  margin: 1rem 0;
}
.sf-muted { color: #666; font-size: 0.9rem; }
</style>
""",
        unsafe_allow_html=True,
    )


def render_beta_footer() -> None:
    st.markdown("---")
    st.caption(BETA_FOOTER_TEXT)


def is_plausible_cnc_text(data: bytes, text: str) -> bool:
    if b"\x00" in data:
        return False
    sample = text[:8000]
    if not sample.strip():
        return False
    printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\r\t")
    return printable / len(sample) >= 0.85


def decode_uploaded_cnc_bytes(data: bytes) -> tuple[str | None, str | None]:
    if not data:
        return None, _CNC_TEXT_ERROR
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            if is_plausible_cnc_text(data, text):
                return text, None
        except UnicodeDecodeError:
            continue
    return None, _CNC_TEXT_ERROR


def inject_preview_chrome(html_doc: str) -> str:
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
  .operation-table-wrap { break-inside: auto; page-break-inside: auto; }
  .operation-table { break-inside: auto; page-break-inside: auto; }
  .operation-table thead { display: table-header-group; }
  .operation-table tbody tr { break-inside: avoid; page-break-inside: avoid; }
  .op-sheet-table td {
    height: auto !important;
    overflow: visible !important;
    white-space: normal !important;
  }
  .op-sheet-table .center-col {
    text-align: center !important;
    vertical-align: middle !important;
  }
  .op-sheet-table .left-col {
    text-align: left !important;
    vertical-align: top !important;
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
.preview-wrapper { background: #ffffff; }
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
.setup-sheet-page { background: #ffffff !important; box-shadow: none; }
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
    return re.sub(
        r"</body>\s*</html>\s*$",
        "</div></body></html>",
        doc_new,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


def session_text(key: str) -> str:
    v = st.session_state.get(key)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s == "-" else s


def build_opsheet_html_from_session() -> str:
    meta = {
        "part_number": session_text("opsheet_part_number"),
        "material": session_text("opsheet_material"),
        "part_description": session_text("opsheet_part_description"),
        "stock_size": session_text("opsheet_stock_size"),
        "customer": session_text("opsheet_customer"),
        "operation_num": session_text("opsheet_operation_num"),
        "program_number": session_text("opsheet_program_number"),
        "created_by": session_text("opsheet_created_by"),
        "machine": session_text("opsheet_machine"),
        "fixture": session_text("opsheet_fixture"),
        "datum_lines": session_text("opsheet_datum_lines"),
        "setup_notes": session_text("opsheet_setup_notes"),
        "prepared_by": session_text("opsheet_prepared_by"),
        "approved_by": session_text("opsheet_approved_by"),
    }
    logo_b64 = None
    logo_mime = None
    lb = st.session_state.get("opsheet_logo_bytes")
    lm_raw = (st.session_state.get("opsheet_logo_mime") or "").split(";")[0].strip().lower()
    allowed_logo = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
    if lb:
        logo_b64 = base64.b64encode(lb).decode("ascii")
        logo_mime = lm_raw if lm_raw in allowed_logo else "image/png"

    return build_one_page_html(
        meta,
        st.session_state["opsheet_op_df"],
        logo_b64=logo_b64,
        logo_mime=logo_mime,
        preserve_operation_order=True,
    )


def build_zip_bytes_from_folder(folder: Path) -> bytes | None:
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


def cnc_extensions_hint() -> str:
    return _CNC_EXTENSIONS_HINT

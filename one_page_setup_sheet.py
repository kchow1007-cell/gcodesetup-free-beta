"""
One-page shop-floor setup sheet HTML (deterministic, no AI).
Excel-style borders; grey / light blue operation section headers.
"""
import html
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from gcode_parser import clean_operation_comment, clean_tool_description

BETA_VERSION_LABEL = "Free Beta v0.1"
BETA_FOOTER_TEXT = (
    "Free Beta v0.1 — Review all extracted data before shop-floor use."
)
BETA_SHOP_FLOOR_WARNING = (
    "This is a beta tool. Always review and edit the extracted setup sheet "
    "before using it on the shop floor."
)
BETA_PRIVACY_NOTE = (
    "Please remove confidential customer, part, and drawing information "
    "before uploading files."
)

_EDITOR_DATA_COLS = (
    "Datum",
    "Tool#",
    "Block#",
    "Operation Comment",
    "Tool Description",
    "H offsets",
    "D offsets",
    "Remark",
)
CLEARABLE_OPERATION_COLUMNS = (
    "Datum",
    "Tool#",
    "Block#",
    "Operation Comment",
    "Tool Description",
    "H offsets",
    "D offsets",
    "Remark",
)
_EDITOR_UI_COLS = ("Select", "Delete?")
_DATUM_SECTION_HEADER_BG = "#b4d7ee"


def _esc(s: Any) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return html.escape(str(s), quote=True)


def _tool_description_from_operation_block(ob: Dict[str, Any]) -> str:
    """
    Tool Description for the one-page sheet comes only from ``operation_blocks``:

    1. ``tool_description_from_header`` (from G-code program header tool table)
    2. ``tool_description`` (parsed/cleaned cutter name)
    3. ``tool_comment`` (raw comment fallback, also cleaned)
    4. blank
    """
    for key in ("tool_description_from_header", "tool_description", "tool_comment"):
        raw = ob.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if not s or s == "-":
            continue
        cleaned = clean_tool_description(s)
        if cleaned:
            return cleaned
    return ""


def _sorted_datums(work_offsets_summary: str, operation_blocks: List[Dict[str, Any]]) -> List[str]:
    """Ordered unique datum strings (G54, G54P1, …)."""
    seen = []
    if work_offsets_summary and work_offsets_summary != "-":
        for part in work_offsets_summary.split(","):
            p = part.strip()
            if p and p not in seen:
                seen.append(p)
    for ob in operation_blocks or []:
        wo = ob.get("work_offsets") or ""
        if wo == "-":
            continue
        for part in wo.split(","):
            p = part.strip()
            if p and p not in seen:
                seen.append(p)
    if not seen:
        seen = ["(no datum detected)"]
    return seen


def normalize_datum_label(datum: Any) -> str:
    """Work-offset token only (e.g. G54, G55, G54P1) — no trailing colon or 'datum' label."""
    d = str(datum or "").strip()
    if not d:
        return d
    d = re.sub(r"\s+datum$", "", d, flags=re.IGNORECASE).strip()
    if d.endswith(":"):
        d = d[:-1].strip()
    return d


def datum_sort_key(datum: Any) -> tuple:
    """
    Sort order: G54–G59, then G54P1/P2/…, then other offsets, then unknown labels.
    """
    d = normalize_datum_label(datum).upper()
    m = re.match(r"^G(\d+)(?:P(\d+))?$", d)
    if not m:
        return (9, 0, 0, d)
    g = int(m.group(1))
    p = int(m.group(2)) if m.group(2) else 0
    if p == 0 and 54 <= g <= 59:
        return (0, g - 54, 0, d)
    if p > 0 and g == 54:
        return (1, p, 0, d)
    return (2, g, p, d)


def block_sort_key(block: Any) -> tuple:
    """Numeric N-block order: N1, N2, N10, …"""
    s = str(block or "").strip().upper()
    if not s or s == "-":
        return (999_999, s)
    m = re.match(r"^N(\d+)$", s)
    if m:
        return (int(m.group(1)), s)
    m = re.match(r"^(\d+)$", s)
    if m:
        return (int(m.group(1)), s)
    return (999_998, s)


def maybe_sort_operation_rows(df: pd.DataFrame, user_modified: bool) -> pd.DataFrame:
    """Sort only when rows are still in initial parsed order (not manually edited)."""
    if user_modified:
        out = strip_editor_ui_columns(df)
        return out.reset_index(drop=True)
    return sort_operation_rows(df)


def sort_operation_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by datum/work offset, then block number within each datum."""
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()
    out = strip_editor_ui_columns(df.copy())
    if "Datum" not in out.columns:
        return out.reset_index(drop=True)
    out["_datum_sort"] = out["Datum"].apply(datum_sort_key)
    if "Block#" in out.columns:
        out["_block_sort"] = out["Block#"].apply(block_sort_key)
    else:
        out["_block_sort"] = [(999_999, "")] * len(out)
    out = out.sort_values(by=["_datum_sort", "_block_sort"], kind="stable")
    return out.drop(columns=["_datum_sort", "_block_sort"]).reset_index(drop=True)


def strip_editor_ui_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove Select / Delete? helper columns before save or preview."""
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()
    drop = [c for c in _EDITOR_UI_COLS if c in df.columns]
    if drop:
        return df.drop(columns=drop)
    return df.copy()


def format_operation_row_label(position: int, row: Any) -> str:
    """e.g. ``1 - G54 - T1 - N1`` for add-row-below picker."""
    if hasattr(row, "get"):
        datum = normalize_datum_label(row.get("Datum", "")) or "?"
        tool = str(row.get("Tool#", "") or "").strip() or "-"
        block = str(row.get("Block#", "") or "").strip() or "-"
    else:
        datum = normalize_datum_label(getattr(row, "Datum", "")) or "?"
        tool = str(getattr(row, "Tool#", "") or "").strip() or "-"
        block = str(getattr(row, "Block#", "") or "").strip() or "-"
    tool_disp = tool if tool.startswith("T") else f"T{tool}"
    block_disp = block if block.upper().startswith("N") else f"N{block}"
    return f"{position + 1} - {datum} - {tool_disp} - {block_disp}"


def insert_blank_row_below(df: pd.DataFrame, position: int) -> pd.DataFrame:
    """Insert one blank row directly below ``position`` (0-based), copying Datum."""
    out = strip_editor_ui_columns(df)
    if out.empty:
        return pd.DataFrame([blank_operation_row("G54")])
    pos = max(0, min(int(position), len(out) - 1))
    datum = normalize_datum_label(out.iloc[pos].get("Datum", "G54")) or "G54"
    new_row = blank_operation_row(datum)
    top = out.iloc[: pos + 1]
    bottom = out.iloc[pos + 1 :]
    merged = pd.concat([top, pd.DataFrame([new_row]), bottom], ignore_index=True)
    return merged.reset_index(drop=True)


def clear_operation_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Blank every cell in ``column`` for all operation rows (editor data columns only)."""
    out = strip_editor_ui_columns(df)
    if out.empty or column not in CLEARABLE_OPERATION_COLUMNS:
        return out.reset_index(drop=True)
    out = out.copy()
    out[column] = ""
    return out.reset_index(drop=True)


def _datum_prefill_from_gcode(result: Optional[Dict[str, Any]]) -> str:
    """One line per detected work offset, with trailing colon (e.g. ``G54:``, ``G56:``)."""
    if not result:
        return ""
    summ = result.get("summary") or {}
    wo = summ.get("work_offsets", "-")
    if not wo or wo == "-":
        return ""
    parts = [p.strip() for p in wo.split(",") if p.strip()]
    parts = sorted(parts, key=datum_sort_key)
    return "\n".join(p + ":" for p in parts)


def _gcode_program_number_prefill(result: Optional[Dict[str, Any]]) -> str:
    """O#### from summary or program header; empty if unknown."""
    if not result:
        return ""
    summ = result.get("summary") or {}
    pn = summ.get("program_number", "-")
    if pn and str(pn).strip() and str(pn) != "-":
        return str(pn).strip()
    ph = result.get("program_header") or {}
    pn2 = ph.get("program_number", "-")
    if pn2 and str(pn2).strip() and str(pn2) != "-":
        return str(pn2).strip()
    return ""


_PREVIEW_CONTENT_COLS = (
    "Tool#",
    "Block#",
    "Operation Comment",
    "Tool Description",
    "H offsets",
    "D offsets",
    "Remark",
)

_FONT_LABEL = "font-size:11px;font-weight:bold;"
_FONT_SECTION = "font-size:11px;font-weight:bold;"
_FONT_BODY = "font-size:10px;"
_FONT_LOGO = "font-size:11px;font-weight:bold;"


def _field_is_blank(val: Any) -> bool:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return True
    s = str(val).strip()
    return s == "" or s == "-"


def is_empty_operation_row(row: Any) -> bool:
    """True when all operation content columns are blank, ``-``, or None."""
    for col in _PREVIEW_CONTENT_COLS:
        if hasattr(row, "get"):
            val = row.get(col)
        else:
            val = row[col] if col in getattr(row, "index", ()) else None
        if not _field_is_blank(val):
            return False
    return True


def filter_empty_operation_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with no operation content (for preview / export only)."""
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()
    mask = ~df.apply(is_empty_operation_row, axis=1)
    return df.loc[mask].reset_index(drop=True)


def blank_operation_row(datum: str = "G54") -> Dict[str, Any]:
    """One empty row for manual entry in the Streamlit editor."""
    return {
        "Datum": datum,
        "Tool#": "",
        "Block#": "",
        "Operation Comment": "",
        "Tool Description": "",
        "H offsets": "",
        "D offsets": "",
        "Remark": "",
    }


def default_datum_for_new_row(df: Optional[pd.DataFrame]) -> str:
    """First non-empty Datum in the table, else G54."""
    if df is not None and not df.empty and "Datum" in df.columns:
        for d in df["Datum"].astype(str).tolist():
            ds = d.strip()
            if ds and ds != "(no datum detected)":
                return ds
    return "G54"


def default_operation_editor_rows(
    result: Dict[str, Any],
    setup_sheet: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Build rows for st.data_editor: one row per (operation block × datum token) when
    multiple work offsets appear in a block; otherwise one row per block.

    **Tool Description** uses only ``operation_blocks`` fields (see
    ``_tool_description_from_operation_block``); setup sheet PDF tool list is not used here.
    """
    blocks = result.get("operation_blocks") or []
    summary_wo = (result.get("summary") or {}).get("work_offsets", "-")
    datums = _sorted_datums(summary_wo, blocks)
    primary = datums[0] if datums else "(no datum detected)"

    rows_out: List[Dict[str, Any]] = []
    for ob in blocks:
        wo_raw = (ob.get("work_offsets") or "-").strip()
        tokens = [t.strip() for t in wo_raw.split(",") if t.strip()] if wo_raw != "-" else []
        if not tokens:
            tokens = [primary]

        d_used = ob.get("d_offset_used") or "-"
        d_hdr = ob.get("d_offset_from_header") or "-"
        d_col = d_used if d_used and d_used != "-" else d_hdr

        tn = ob.get("tool_number") or "-"
        tdesc = _tool_description_from_operation_block(ob)

        for datum in tokens:
            rows_out.append(
                {
                    "Datum": datum,
                    "Tool#": tn,
                    "Block#": ob.get("block_number") or "-",
                    "Operation Comment": clean_operation_comment(
                        ob.get("operation_comment"), ob.get("block_number")
                    )
                    or "-",
                    "Tool Description": tdesc,
                    "H offsets": ob.get("h_offset") or "-",
                    "D offsets": d_col,
                    "Remark": "",
                }
            )

    if not rows_out:
        rows_out.append(
            {
                "Datum": primary,
                "Tool#": "-",
                "Block#": "-",
                "Operation Comment": "-",
                "Tool Description": "",
                "H offsets": "-",
                "D offsets": "-",
                "Remark": "",
            }
        )

    return sort_operation_rows(pd.DataFrame(rows_out))


def default_metadata(result=None, setup_sheet=None) -> Dict[str, str]:
    """
    Defaults for the one-page sheet.

    Most header fields stay empty for manual entry. **PROGRAM#** and **DATUM**
    are prefilled from parsed G-code (program number / work offsets) when
    available; both remain editable in the app.
    """
    prog = _gcode_program_number_prefill(result) if result else ""
    datum = _datum_prefill_from_gcode(result) if result else ""
    return {
        "part_number": "",
        "material": "",
        "part_description": "",
        "stock_size": "",
        "customer": "",
        "operation_num": "",
        "program_number": prog,
        "created_by": "",
        "machine": "",
        "fixture": "",
        "datum_lines": datum,
        "setup_notes": "",
        "prepared_by": "",
        "approved_by": "",
    }


_OP_TABLE_COLGROUP = (
    "<colgroup>"
    '<col style="width:6%" /><col style="width:7%" /><col style="width:43%" />'
    '<col style="width:26%" /><col style="width:7%" /><col style="width:7%" /><col style="width:10%" />'
    "</colgroup>"
)


def group_editor_rows_by_datum(
    df: pd.DataFrame,
    preserve_order: bool = False,
) -> List[Tuple[str, pd.DataFrame]]:
    """Return (datum, rows) groups; sorted by offset unless ``preserve_order``."""
    if df is None or df.empty:
        return []
    work = strip_editor_ui_columns(df).reset_index(drop=True)
    if not preserve_order:
        work = sort_operation_rows(work)
        unique = sorted(
            {normalize_datum_label(d) for d in work["Datum"].astype(str).tolist() if str(d).strip()},
            key=datum_sort_key,
        )
    else:
        unique = []
        seen = set()
        for d in work["Datum"].astype(str).tolist():
            nd = normalize_datum_label(d)
            if nd and nd not in seen:
                seen.add(nd)
                unique.append(nd)
    out: List[Tuple[str, pd.DataFrame]] = []
    for d in unique:
        sub = work[work["Datum"].astype(str).apply(normalize_datum_label) == d].copy()
        if not sub.empty:
            out.append((d, sub))
    return out


def build_one_page_html(
    meta: Dict[str, str],
    op_df: pd.DataFrame,
    logo_b64: Optional[str] = None,
    logo_mime: Optional[str] = None,
    preserve_operation_order: bool = False,
) -> str:
    """
    meta keys include: part_number, material, part_description, stock_size, customer,
    operation_num, program_number, created_by, machine, fixture, datum_lines, setup_notes,
    prepared_by, approved_by.
    """
    allowed_logo_mimes = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
    preview_df = filter_empty_operation_rows(op_df)
    if not preserve_operation_order:
        preview_df = sort_operation_rows(preview_df)
    grouped = group_editor_rows_by_datum(preview_df, preserve_order=preserve_operation_order)

    if logo_b64 and logo_mime:
        safe_mime = logo_mime if logo_mime in allowed_logo_mimes else "image/png"
        logo_inner = f'<img src="data:{safe_mime};base64,{logo_b64}" alt="Logo" />'
    else:
        logo_inner = (
            '<span class="logo-placeholder">'
            '<span class="logo-text-screen">COMPANY LOGO</span>'
            '<span class="logo-text-print">LOGO</span>'
            "</span>"
        )
    logo_html = f'<div class="logo-box">{logo_inner}</div>'

    def _hv(lbl: str, val: str) -> str:
        return (
            f'<td style="border:1px solid #000;padding:2px 5px;background:#f0f0f0;{_FONT_LABEL}'
            f'white-space:nowrap;width:1%;">{_esc(lbl)}</td>'
            f'<td style="border:1px solid #000;padding:2px 5px;{_FONT_BODY}">{_esc(val)}</td>'
        )

    top_right_rows = "".join(
        [
            "<tr>"
            + _hv("PART#", meta.get("part_number", ""))
            + _hv("PART DESCRIPTION", meta.get("part_description", ""))
            + "</tr>",
            "<tr>"
            + _hv("CUSTOMER", meta.get("customer", ""))
            + _hv("MATERIAL", meta.get("material", ""))
            + "</tr>",
            "<tr>"
            + _hv("OPERATION#", meta.get("operation_num", ""))
            + _hv("STOCK SIZE", meta.get("stock_size", ""))
            + "</tr>",
            "<tr>"
            + _hv("PROGRAM#", meta.get("program_number", ""))
            + _hv("CREATED BY", meta.get("created_by", ""))
            + "</tr>",
        ]
    )

    machine = meta.get("machine", "")
    fixture = meta.get("fixture", "")
    dl_raw = meta.get("datum_lines", "") or ""
    datum_lines_html = "<br/>".join(_esc(x) for x in dl_raw.splitlines())
    setup_notes_html = _esc(meta.get("setup_notes", "")).replace("\n", "<br/>")

    def _cell(val: Any) -> str:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        return _esc(val)

    op_sections_html = []
    for datum_label, sub in grouped:
        if sub is None or sub.empty:
            continue
        title = _esc(normalize_datum_label(datum_label))

        body_rows = []
        for _, r in sub.iterrows():
            rem = r.get("Remark")
            if rem is None or (isinstance(rem, float) and pd.isna(rem)):
                rem = ""
            body_rows.append(
                "<tr>"
                f"<td>{_cell(r.get('Tool#'))}</td>"
                f"<td>{_cell(r.get('Block#'))}</td>"
                f"<td>{_cell(r.get('Operation Comment'))}</td>"
                f"<td>{_cell(r.get('Tool Description'))}</td>"
                f"<td>{_cell(r.get('H offsets'))}</td>"
                f"<td>{_cell(r.get('D offsets'))}</td>"
                f"<td>{_cell(rem)}</td>"
                "</tr>"
            )

        op_sections_html.append(
            '<div class="operation-section">'
            '<table class="op-sheet-table operation-table">'
            + _OP_TABLE_COLGROUP
            + "<thead>"
            + f'<tr class="operation-section-title"><td colspan="7">{title}</td></tr>'
            + "<tr>"
            + f'<th>Tool#</th>'
            + f'<th>Block#</th>'
            + f'<th>Operation Comment</th>'
            + f'<th>Tool Description</th>'
            + f'<th>H offsets</th>'
            + f'<th>D offsets</th>'
            + f'<th>Remark</th>'
            + "</tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table></div>"
        )

    op_style = """<style type="text/css">
@media print {
  @page { size: letter portrait; margin: 0.25in; }
  body { margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .setup-sheet-page { width: 100%; max-width: none; box-shadow: none; border: none; padding: 0; }
  .no-print { display: none !important; }
  .logo-cell {
    width: 150px !important; min-width: 150px !important; max-width: 150px !important;
    height: 85px !important;
  }
  .logo-box {
    width: 100% !important; height: 100% !important; overflow: hidden !important;
  }
  .logo-text-screen { display: none !important; }
  .logo-text-print { display: inline !important; }
  .operation-section { break-inside: auto; page-break-inside: auto; }
  .operation-section:first-of-type { margin-top: 6px; page-break-before: auto; break-before: auto; }
  .operation-table { break-inside: auto; page-break-inside: auto; }
  .operation-section-title { break-after: avoid; page-break-after: avoid; }
  .operation-table thead { display: table-header-group; }
  tr { break-inside: avoid; page-break-inside: avoid; }
}
.setup-sheet-page { font-family: Arial, Helvetica, sans-serif; background: #fff; color: #000; }
.header-table { width: 100%; table-layout: fixed; border-collapse: collapse; }
.logo-cell {
  width: 150px; min-width: 150px; max-width: 150px; height: 85px; padding: 4px;
  box-sizing: border-box; vertical-align: middle; text-align: center;
  border: 1px solid #000;
}
.logo-box {
  width: 100%; height: 100%; border: 1px dashed #777; display: flex; align-items: center;
  justify-content: center; box-sizing: border-box; overflow: hidden; text-align: center;
}
.logo-box img {
  max-width: 100%; max-height: 100%; object-fit: contain; display: block;
}
.logo-placeholder {
  font-size: 11px; font-weight: bold; line-height: 1.1; white-space: normal; max-width: 100%;
  padding: 2px;
}
.logo-text-screen { display: inline; }
.logo-text-print { display: none; }
.machine-datum-box { min-height: 55px; max-height: 55px; overflow: hidden; padding: 4px 6px;
  font-size: 10px; box-sizing: border-box; }
.setup-notes-box { min-height: 70px; max-height: 70px; overflow: hidden; padding: 4px 6px;
  font-size: 10px; line-height: 1.25; box-sizing: border-box; }
.sheet-header-table td { padding: 2px 5px; }
.sheet-section-title { font-size: 11px; font-weight: bold; background: #d9d9d9; padding: 2px 5px;
  border-bottom: 1px solid #000; }
.sheet-section-body { font-size: 10px; padding: 4px 6px; }
.machine-fixture-row { margin-top: 6px; }
.setup-notes-wrap { margin-top: 6px; border: 1px solid #000; }
.operation-section { margin-top: 8px; break-inside: auto; }
.operation-section:first-of-type { margin-top: 6px; page-break-before: auto; break-before: auto; }
.op-sheet-table { table-layout: fixed; width: 100%; border-collapse: collapse; margin-top: 0; }
.op-sheet-table th { font-size: 10px; font-weight: bold; border: 1px solid #000; padding: 2px 4px;
  height: 16px; vertical-align: middle; box-sizing: border-box; background: #e8e8e8; }
.op-sheet-table td { font-size: 9px; border: 1px solid #000; padding: 2px 4px; height: 16px;
  vertical-align: middle; box-sizing: border-box; overflow: hidden; word-wrap: break-word; }
.operation-section-title td { background: #b4d7ee; font-size: 11px; font-weight: bold; text-align: center;
  padding: 4px; border: 1px solid #000; break-after: avoid; page-break-after: avoid; }
.operation-table thead { display: table-header-group; }
.prepared-row { margin-top: 6px; font-size: 10px; }
.prepared-row td { padding: 4px 6px; border: 1px solid #000; }
.sheet-beta-footer {
  margin-top: 10px; padding: 6px 8px; font-size: 9px; color: #444;
  text-align: center; border-top: 1px solid #ccc;
}
</style>"""

    full = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Setup Sheet</title>
{op_style}</head>
<body style="margin:8px;font-family:Arial,Helvetica,sans-serif;background:#fff;color:#000;">
<div class="setup-sheet-page">
<table class="header-table" style="border:2px solid #000;">
<tr>
<td class="logo-cell">{logo_html}</td>
<td style="vertical-align:top;border:1px solid #000;padding:0;">
<table style="width:100%;border-collapse:collapse;">{top_right_rows}</table>
</td>
</tr>
</table>

<table class="machine-fixture-row" style="width:100%;border-collapse:collapse;table-layout:fixed;">
<tr>
<td style="width:50%;border:1px solid #000;padding:0;vertical-align:top;">
<table style="width:100%;border-collapse:collapse;table-layout:fixed;">
<tr>
<td style="width:50%;border-right:1px solid #000;padding:0;vertical-align:top;">
<div class="sheet-section-title">MACHINE</div>
<div class="sheet-section-body machine-datum-box">{_esc(machine)}</div>
</td>
<td style="width:50%;padding:0;vertical-align:top;">
<div class="sheet-section-title">FIXTURE</div>
<div class="sheet-section-body machine-datum-box">{_esc(fixture)}</div>
</td>
</tr>
</table>
</td>
<td style="width:50%;border:1px solid #000;padding:0;vertical-align:top;">
<div class="sheet-section-title">DATUM</div>
<div class="sheet-section-body machine-datum-box">{datum_lines_html}</div>
</td>
</tr>
</table>

<div class="setup-notes-wrap">
<div class="sheet-section-title">SETUP NOTES</div>
<div class="sheet-section-body setup-notes-box">{setup_notes_html}</div>
</div>

{"".join(op_sections_html)}

<table class="prepared-row" style="width:100%;border-collapse:collapse;">
<tr>
<td style="width:50%;{_FONT_BODY}">Prepared By: {_esc(meta.get("prepared_by",""))}</td>
<td style="width:50%;{_FONT_BODY}">Approved By: {_esc(meta.get("approved_by",""))}</td>
</tr>
</table>
<p class="sheet-beta-footer">{_esc(BETA_FOOTER_TEXT)}</p>
</div>
</body></html>"""
    return full

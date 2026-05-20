"""
Local feedback log and optional problem-sample storage.

Folder layout (created automatically on first submit):

    feedback/
        feedback_log.csv    — one row per submission
        uploads/            — uploaded CNC problem files
        snippets/           — pasted G-code snippets
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FEEDBACK_ROOT = Path(__file__).resolve().parent / "feedback"
UPLOADS_DIR = FEEDBACK_ROOT / "uploads"
SNIPPETS_DIR = FEEDBACK_ROOT / "snippets"
CSV_PATH = FEEDBACK_ROOT / "feedback_log.csv"

CSV_COLUMNS = [
    "timestamp",
    "parser_result",
    "issue_categories",
    "control_type",
    "cam_post",
    "description",
    "uploaded_filename",
    "snippet_filename",
    "consent_confidential",
    "consent_improvement",
]

FEEDBACK_PRIVACY_NOTE = (
    "Please remove confidential customer, part, and drawing information "
    "before sharing files or code snippets."
)

FEEDBACK_SUBMIT_SUCCESS = (
    "Thank you — feedback saved. If you uploaded a file, "
    "it was saved for parser improvement."
)

FEEDBACK_SUBMIT_SUCCESS_NO_UPLOAD = "Thank you — feedback saved."

_ALLOWED_SAMPLE_EXTENSIONS = {
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


def ensure_feedback_dirs() -> None:
    FEEDBACK_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_basename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-]+", "_", base).strip("._")
    return (base or "upload")[:120]


def is_allowed_sample_filename(filename: str) -> bool:
    """Allow known CNC extensions or files with no extension."""
    suffix = Path(filename).suffix.lower()
    return suffix in _ALLOWED_SAMPLE_EXTENSIONS or suffix == ""


def save_problem_upload(data: bytes, original_name: str) -> str:
    """Save uploaded bytes to ``feedback/uploads/``; return relative path."""
    ensure_feedback_dirs()
    safe = _safe_basename(original_name)
    stored = f"{_file_stamp()}_{safe}"
    (UPLOADS_DIR / stored).write_bytes(data)
    return f"uploads/{stored}"


def save_problem_snippet(text: str) -> str:
    """Save pasted snippet to ``feedback/snippets/``; return relative path."""
    ensure_feedback_dirs()
    stored = f"{_file_stamp()}_snippet.txt"
    (SNIPPETS_DIR / stored).write_text(text, encoding="utf-8")
    return f"snippets/{stored}"


def append_feedback_row(row: dict[str, Any]) -> None:
    ensure_feedback_dirs()
    write_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    with CSV_PATH.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})


def record_feedback(
    *,
    parser_result: str,
    issue_categories: list[str],
    control_type: str,
    cam_post: str,
    description: str,
    consent_confidential: bool,
    consent_improvement: bool,
    upload_bytes: Optional[bytes] = None,
    upload_name: Optional[str] = None,
    snippet_text: Optional[str] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """
    Append row to ``feedback/feedback_log.csv``.
    Save upload/snippet under ``feedback/uploads/`` and ``feedback/snippets/``
    only when both consent boxes are checked.

    Returns (timestamp, uploaded_path_or_none, snippet_path_or_none).
    """
    ensure_feedback_dirs()
    ts = _utc_timestamp()
    both_consent = consent_confidential and consent_improvement
    uploaded_filename = None
    snippet_filename = None

    if both_consent and upload_bytes and upload_name:
        if is_allowed_sample_filename(upload_name):
            uploaded_filename = save_problem_upload(upload_bytes, upload_name)
        else:
            uploaded_filename = ""

    if both_consent and snippet_text and snippet_text.strip():
        snippet_filename = save_problem_snippet(snippet_text.strip())

    append_feedback_row(
        {
            "timestamp": ts,
            "parser_result": parser_result,
            "issue_categories": "; ".join(issue_categories),
            "control_type": control_type,
            "cam_post": cam_post,
            "description": (description or "").strip(),
            "uploaded_filename": uploaded_filename or "",
            "snippet_filename": snippet_filename or "",
            "consent_confidential": "yes" if consent_confidential else "no",
            "consent_improvement": "yes" if consent_improvement else "no",
        }
    )
    return ts, uploaded_filename, snippet_filename

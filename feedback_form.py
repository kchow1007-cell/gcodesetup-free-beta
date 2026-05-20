"""
Streamlit UI: parser feedback and optional problem samples.
"""
from __future__ import annotations

import streamlit as st

from feedback_storage import (
    FEEDBACK_PRIVACY_NOTE,
    FEEDBACK_SUBMIT_SUCCESS,
    FEEDBACK_SUBMIT_SUCCESS_NO_UPLOAD,
    is_allowed_sample_filename,
    record_feedback,
)

_PARSER_RESULT_OPTIONS = ("Yes", "Partially", "No")

_ISSUE_OPTIONS = [
    "Tool number wrong",
    "Block number wrong",
    "Operation comment wrong",
    "Tool description wrong",
    "H/D offset wrong",
    "Datum/work offset grouping wrong",
    "File could not upload",
    "Preview/print issue",
    "Other",
]

_CONTROL_OPTIONS = [
    "Not sure",
    "Fanuc / Haas",
    "Siemens / MPF",
    "Makino",
    "Heidenhain",
    "Brother",
    "Mazak",
    "Other",
]

_CAM_OPTIONS = [
    "Not sure",
    "Mastercam",
    "Fusion",
    "NX",
    "SolidCAM",
    "Esprit",
    "Other",
]

def render_parser_feedback_form() -> None:
    st.divider()
    st.subheader("Help Improve the Parser")
    st.caption(
        "Tell us what worked and what did not. You can optionally share a short "
        "G-code sample so we can improve parsing rules."
    )
    st.info(FEEDBACK_PRIVACY_NOTE)

    with st.form("parser_feedback_form", clear_on_submit=True):
        parser_result = st.radio(
            "Did the parser work?",
            options=_PARSER_RESULT_OPTIONS,
            horizontal=True,
            index=0,
        )

        issues = st.multiselect(
            "What issue did you see? (select all that apply)",
            options=_ISSUE_OPTIONS,
        )

        c1, c2 = st.columns(2)
        with c1:
            control_type = st.selectbox("CNC control / machine type", options=_CONTROL_OPTIONS)
        with c2:
            cam_post = st.selectbox("CAM software / post", options=_CAM_OPTIONS)

        description = st.text_area(
            "Describe the issue",
            placeholder="Example: Tool description on the M06 line was correct, but the operation comment came from the wrong line.",
            height=100,
        )

        st.markdown("**Share a problem sample (optional)**")

        problem_file = st.file_uploader(
            "A. Upload problem CNC file",
            help="Recommended. Uploading the original file preserves spacing, line breaks, extension, and format.",
        )
        st.caption(
            "Allowed: .nc, .txt, .tap, .gcode, .mpf, .min, .eia, .cnc, .h — or no extension."
        )

        snippet = st.text_area(
            "B. Paste problem G-code snippet",
            placeholder="Paste 20–80 lines around the section that parsed incorrectly.",
            height=140,
        )
        st.caption(
            "Paste 20–80 lines around the section that parsed incorrectly."
        )

        consent_confidential = st.checkbox(
            "I confirm this file/snippet does not contain confidential customer data, "
            "or I have permission to share it for parser improvement.",
        )
        consent_improvement = st.checkbox(
            "You may use this sample to improve parser rules.",
        )

        submitted = st.form_submit_button("Submit Feedback", type="primary")

    if not submitted:
        return

    has_sample = bool(problem_file) or bool((snippet or "").strip())
    both_consent = consent_confidential and consent_improvement

    if has_sample and not both_consent:
        st.warning(
            "Your feedback was recorded, but the file/snippet was **not saved** because "
            "both consent boxes must be checked to store samples."
        )

    upload_bytes = None
    upload_name = None
    if problem_file and both_consent:
        upload_bytes = problem_file.getvalue()
        upload_name = problem_file.name
        if not is_allowed_sample_filename(upload_name):
            st.error(
                f"File type not allowed: `{upload_name}`. "
                "Use a standard CNC extension or a file with no extension."
            )
            upload_bytes = None
            upload_name = None

    snippet_text = (snippet or "").strip() if both_consent else ""

    _ts, uploaded_name, snippet_name = record_feedback(
        parser_result=parser_result,
        issue_categories=issues,
        control_type=control_type,
        cam_post=cam_post,
        description=description,
        consent_confidential=consent_confidential,
        consent_improvement=consent_improvement,
        upload_bytes=upload_bytes,
        upload_name=upload_name,
        snippet_text=snippet_text or None,
    )

    if uploaded_name:
        st.success(FEEDBACK_SUBMIT_SUCCESS)
    else:
        st.success(FEEDBACK_SUBMIT_SUCCESS_NO_UPLOAD)
    if snippet_name and not uploaded_name:
        st.caption(f"Snippet saved to `{snippet_name}`.")
    if has_sample and not both_consent:
        st.caption("No sample file or snippet was stored (consent required).")

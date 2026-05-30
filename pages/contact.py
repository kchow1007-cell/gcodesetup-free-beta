"""Contact / Feedback."""
import streamlit as st

from app_shared import apply_app_styles, render_beta_footer
from feedback_form import render_parser_feedback_form

apply_app_styles()

st.title("Contact / Feedback")
st.markdown(
    """
<p class="sf-page-intro">
  Your feedback helps us improve parsing for real shop-floor programs — Fanuc, Siemens,
  Fusion, Mastercam, Makino, Brother, and more.
</p>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="sf-card">
  <h3>We want to hear from you</h3>
  <p style="margin:0;line-height:1.5;">
    Tell us what worked, what was wrong, and optionally share a short G-code sample
    (with confidential data removed). Use the form below after you try the tool on
    <strong>Home / Tool</strong>.
  </p>
</div>
<div class="sf-card">
  <h3>For companies</h3>
  <p style="margin:0;line-height:1.5;">
    For confidential company templates or custom parser support, please contact us for
    <strong>private/local deployment</strong> options. Custom setup sheet layouts and
    post-specific parsers can run on your network without sending programs to the cloud.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

render_parser_feedback_form()
render_beta_footer()

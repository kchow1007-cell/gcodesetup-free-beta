"""Plans — Free Beta, Pro, and custom options."""
import streamlit as st

from app_shared import apply_app_styles, render_beta_footer
from one_page_setup_sheet import BETA_VERSION_LABEL

apply_app_styles()

st.title("Plans")
st.markdown(
    '<p class="sf-page-intro">Simple pricing tiers for CNC shops and programmers. '
    f'{BETA_VERSION_LABEL} is available now — no login required.</p>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="sf-card">
  <h3>Free Beta</h3>
  <ul>
    <li>G-code upload</li>
    <li>Editable one-page setup sheet</li>
    <li>Print / save as PDF</li>
    <li>Feedback support</li>
  </ul>
</div>
<div class="sf-card">
  <h3>Pro — Coming Soon</h3>
  <ul>
    <li>Saved setup sheet templates</li>
    <li>Company logo</li>
    <li>Direct PDF export</li>
    <li>Detailed tool page</li>
    <li>Parser profiles for different CNC posts</li>
  </ul>
</div>
<div class="sf-card">
  <h3>Shop / Custom</h3>
  <ul>
    <li>Company-specific setup sheet template</li>
    <li>Custom post parser</li>
    <li>Private/local deployment for confidential programs</li>
  </ul>
</div>
<div class="sf-note">
  <strong>Public beta:</strong> The public beta is for non-confidential testing only.
  Remove customer, part, and drawing details before uploading files.
</div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    "Use **Home / Tool** in the sidebar to upload G-code and build your setup sheet today."
)
render_beta_footer()

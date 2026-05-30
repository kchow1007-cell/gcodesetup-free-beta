"""About GcodeSetup."""
import streamlit as st

from app_shared import apply_app_styles, render_beta_footer
from one_page_setup_sheet import BETA_VERSION_LABEL

apply_app_styles()

st.title("About")
st.markdown(
    f'<p class="sf-page-intro">{BETA_VERSION_LABEL}</p>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="sf-card">
  <p style="margin:0;line-height:1.5;">
    <strong>GcodeSetup</strong> is a beta tool built to help CNC programmers, machinists,
    and manufacturing engineers create quick shop-floor setup sheets from posted G-code.
  </p>
</div>
<div class="sf-card">
  <h3>What it extracts</h3>
  <ul>
    <li>Tool number</li>
    <li>Block number</li>
    <li>Operation comments</li>
    <li>Tool descriptions</li>
    <li>H/D offsets</li>
    <li>Datum / work offset grouping</li>
  </ul>
</div>
<div class="sf-note">
  <strong>Beta reminder:</strong> The tool is still in beta. Always review extracted data
  before use on the shop floor.
</div>
<p class="sf-muted">
  GcodeSetup does not replace your CAM system or machine setup documentation — it helps you
  turn posted programs into a readable one-page sheet faster.
</p>
""",
    unsafe_allow_html=True,
)

render_beta_footer()

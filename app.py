"""
GcodeSetup — multi-page Streamlit app entry point.
"""
import streamlit as st

from app_shared import apply_app_styles
from one_page_setup_sheet import BETA_VERSION_LABEL

st.set_page_config(
    page_title=f"GcodeSetup — CNC Setup Sheet ({BETA_VERSION_LABEL})",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_app_styles()

pages = [
    st.Page("pages/home.py", title="Home / Tool", default=True),
    st.Page("pages/plans.py", title="Plans"),
    st.Page("pages/about.py", title="About"),
    st.Page("pages/contact.py", title="Contact / Feedback"),
]

pg = st.navigation(pages, position="top")
pg.run()

import os
import json
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="The Way In — Another Idea",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

COMPONENT_DIR = Path(__file__).parent / "the_way_in_component"
the_way_in = components.declare_component("the_way_in", path=str(COMPONENT_DIR))


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = os.getenv(name, default)
    return str(value or "")


def send_email(payload: dict) -> None:
    smtp_user = get_secret("SMTP_USER")
    smtp_pass = get_secret("SMTP_PASS")
    email_to = get_secret("EMAIL_TO", "gauravgandhi@anotheridea.in")

    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP_USER or SMTP_PASS is not configured.")

    client = str(payload.get("client") or "Untitled").strip()
    ref = str(payload.get("ref") or "").strip()
    markdown = str(payload.get("markdown") or "")

    subject = f"New The Way In Submission | {client}"
    if ref:
        subject += f" | {ref}"

    msg = MIMEMultipart("alternative")
    msg["From"] = f"The Way In <{smtp_user}>"
    msg["To"] = email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(markdown, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.sendmail(smtp_user, [email_to], msg.as_string())


def payload_fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# Small CSS layer for the Streamlit shell. The actual questionnaire styling is in the component HTML.
st.markdown(
    """
    <style>
    [data-testid="stHeader"] { display: none; }
    [data-testid="stToolbar"] { display: none; }
    .block-container { padding-top: 0 !important; padding-left: 0 !important; padding-right: 0 !important; max-width: 100% !important; }
    footer { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

payload = the_way_in(key="the-way-in-questionnaire")

if isinstance(payload, dict) and payload.get("action") == "submit":
    fingerprint = payload_fingerprint(payload)
    if st.session_state.get("last_submission") != fingerprint:
        try:
            send_email(payload)
            st.session_state["last_submission"] = fingerprint
            st.session_state["submission_status"] = "success"
        except Exception as exc:
            st.session_state["submission_status"] = str(exc)

status = st.session_state.get("submission_status")
if status == "success":
    st.success("Answers sent successfully to Another Idea.")
elif status and status != "success":
    st.error(f"Could not send the answers: {status}")

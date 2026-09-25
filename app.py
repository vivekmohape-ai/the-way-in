from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

import streamlit as st


st.set_page_config(
    page_title="The Way In — Another Idea",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)


SOURCE = Path(__file__).with_name("original.html")


def extract_source_parts(source: str) -> tuple[str, str, str]:
    style_match = re.search(r"<style>(.*?)</style>", source, flags=re.S | re.I)
    body_match = re.search(r"<body>(.*?)<script>", source, flags=re.S | re.I)
    script_match = re.search(r"<script>(.*?)</script>", source, flags=re.S | re.I)

    if not (style_match and body_match and script_match):
        raise RuntimeError(
            "The original HTML structure is missing its style, body, or script block."
        )

    return style_match.group(1), body_match.group(1), script_match.group(1)


def build_frontend(source: str) -> tuple[str, str, str]:
    css, body, original_js = extract_source_parts(source)

    css = (
        '@import url("https://fonts.googleapis.com/css2?family=Host+Grotesk:wght@300;400;500;600&family=Inter+Tight:wght@300;400;500;600&display=swap");\n'
        + css
        + """
/* Streamlit host reset */
[data-testid="stMainBlockContainer"] {
    max-width: none !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
}

.twi-streamlit-root {
    width: 100%;
    min-width: 0;
}
"""
    )

    backend_start = original_js.find(
        'const toastEl = document.getElementById("toast")'
    )
    if backend_start < 0:
        raise RuntimeError(
            "Could not locate the original submission integration in the HTML."
        )

    core_js = original_js[:backend_start]

    # IMPORTANT: setupServicingDropdown() has its own local variable named `root`.
    # The Streamlit V2 wrapper also exposes a component root named `root`, and the
    # generic DOM scoping below rewrites document.getElementById(...) to
    # root.querySelector(...). Rename the dropdown helper's local root first,
    # independent of function order, so it can never become:
    # const root = root.querySelector(...)
    servicing_match = re.search(
        r"function setupServicingDropdown\(\)\{.*?(?=\nfunction \w+\()",
        core_js,
        flags=re.S,
    )
    if servicing_match:
        servicing_block = servicing_match.group(0)
        servicing_block = re.sub(r"\broot\b", "servicingRoot", servicing_block)
        core_js = (
            core_js[:servicing_match.start()]
            + servicing_block
            + core_js[servicing_match.end():]
        )

    # Scope normal DOM lookups to the Streamlit V2 component root.
    core_js = re.sub(
        r'document\.getElementById\(("[^"]+")\)',
        lambda m: 'root.querySelector("#' + m.group(1)[1:-1] + '")',
        core_js,
    )
    core_js = core_js.replace("document.querySelectorAll(", "root.querySelectorAll(")
    core_js = core_js.replace("document.querySelector(", "root.querySelector(")

    if "const root = root.querySelector" in core_js:
        raise RuntimeError(
            "Invalid Client Servicing root scoping generated in frontend JavaScript."
        )

    core_js += r'''

const toastEl = root.querySelector("#toast");
const statusEl = root.querySelector("#status");

const toast = m => {
    toastEl.textContent = m;
    toastEl.classList.add("show");
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(
        () => toastEl.classList.remove("show"),
        2600
    );
};

const sendBtn = root.querySelector("#sendBtn");
const dlBtn = root.querySelector("#dlBtn");

sendBtn.hidden = false;
dlBtn.hidden = false;
dlBtn.textContent = "Download your answers";

sendBtn.onclick = () => {
    if(!filled(state.client)) {
        statusEl.textContent = "Add the brand name at the top before sending.";
        root.querySelector('[data-key="client"]').focus();
        return;
    }

    if(!filled(state.servicing)) {
        statusEl.textContent = "Select the Client Servicing person before sending.";
        root.querySelector('[data-key="servicing"] .servicing-trigger').focus();
        return;
    }

    sendBtn.disabled = true;
    statusEl.textContent = "Sending…";
    setTriggerValue("submit", payload());
};

// Direct browser download from the visible button beside Send answers.
// The click originates from the user's gesture, so the browser treats it as
// an allowed download rather than a background action.
dlBtn.onclick = () => {
    const slug = (state.client || "answers")
        .replace(/[^\w\- ]+/g, "")
        .trim()
        .replace(/\s+/g, "-") || "answers";

    try {
        const blob = new Blob([toMarkdown()], {type: "text/markdown;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "Brand-Questionnaire-" + slug + ".md";
        a.style.display = "none";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        statusEl.textContent = "Your answers were downloaded.";
        toast("Answers downloaded.");
    } catch(e) {
        statusEl.textContent = "Couldn’t download your answers. Please try again.";
    }
};

if(data?.send_status === "success") {
    sendBtn.disabled = false;
    statusEl.textContent =
        "Answers sent to Another Idea. You can keep editing and send again.";
    toast("Answers sent.");
}
else if(data?.send_status === "error") {
    sendBtn.disabled = false;
    statusEl.textContent =
        "Couldn’t send. Check the Streamlit SMTP secrets and try again.";
}
'''

    # The HTML already initializes the dropdown and date picker in its own script.
    # We execute those helpers after the Streamlit wrapper has defined root.
    core_js += r'''

render();
update();
setupServicingDropdown();
setupDatePicker();
watchChapters();
'''

    js = """
export default function(component) {
    const {
        parentElement,
        setTriggerValue,
        data
    } = component;

    const root = parentElement;

""" + core_js + """
}
"""

    body = '<div class="twi-streamlit-root">' + body + "</div>"
    return body, css, js


@st.cache_resource(show_spinner=False)
def frontend(source_mtime_ns: int) -> tuple[str, str, str]:
    return build_frontend(SOURCE.read_text(encoding="utf-8"))


def send_email(payload: dict) -> None:
    smtp_user = st.secrets.get("SMTP_USER", "hr@anotheridea.in")
    smtp_pass = st.secrets["SMTP_PASS"]

    servicing_secret_keys = {
        "Adnan Taraporwala": "ADNAN_EMAIL",
        "Ashish Pawar": "ASHISH_EMAIL",
        "Barkha Khandelwal": "BARKHA_EMAIL",
        "Bhumi Jain": "BHUMI_EMAIL",
        "Kedar Bhosle": "KEDAR_EMAIL",
        "Mayank Bheda": "MAYANK_EMAIL",
        "Nayan Chudasama": "NAYAN_EMAIL",
        "Prachi Joshi": "PRACHI_EMAIL",
        "Sarvesh Gawade": "SARVESH_EMAIL",
    }

    servicing_person = (payload.get("servicing") or "").strip()
    secret_key = servicing_secret_keys.get(servicing_person)
    if not secret_key:
        raise ValueError("Invalid or missing Client Servicing selection")

    servicing_email = st.secrets[secret_key].strip()

    fixed_recipients = [
        x.strip()
        for x in st.secrets["FIXED_RECIPIENTS"].split(",")
        if x.strip()
    ]

    cc_recipients = [
        email
        for email in fixed_recipients
        if email.lower() != servicing_email.lower()
    ]

    client = payload.get("client") or "Untitled"
    ref = payload.get("ref") or "No reference"

    subject = f"The Way In submission | {client} | {ref}"

    markdown = payload.get("markdown") or "No answers submitted."

    plain = (
        "The Way In — Another Idea\n\n"
        f"Brand: {client}\n"
        f"Manager: {payload.get('manager') or '—'}\n"
        f"Client Servicing: {servicing_person}\n"
        f"Reference: {ref}\n"
        f"Date: {payload.get('date') or '—'}\n"
        f"Submitted at: {payload.get('submittedAt') or '—'}\n\n"
        f"{markdown}\n"
    )

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = servicing_email
    if cc_recipients:
        msg["Cc"] = ", ".join(cc_recipients)
    msg["Subject"] = subject
    msg.set_content(plain)

    smtp_host = st.secrets.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(st.secrets.get("SMTP_PORT", 465))

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)


HTML, CSS, JS = frontend(SOURCE.stat().st_mtime_ns)

component = st.components.v2.component(
    name="another_idea_the_way_in_v2",
    html=HTML,
    css=CSS,
    js=JS,
    isolate_styles=False,
)

send_status = st.session_state.pop("twi_send_status", None)

result = component(
    key="the-way-in-questionnaire-v2",
    data={"send_status": send_status},
    width="stretch",
    height="content",
    on_submit_change=lambda: None,
)

# Handle email submission.
if getattr(result, "submit", None):
    payload = result.submit

    try:
        send_email(payload)
        st.session_state["twi_send_status"] = "success"
    except Exception:
        st.session_state["twi_send_status"] = "error"

    st.rerun()

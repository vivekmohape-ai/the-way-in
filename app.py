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
    style_match = re.search(
        r"<style>(.*?)</style>",
        source,
        flags=re.S | re.I,
    )

    body_match = re.search(
        r"<body>(.*?)<script>",
        source,
        flags=re.S | re.I,
    )

    script_match = re.search(
        r"<script>(.*?)</script>",
        source,
        flags=re.S | re.I,
    )

    if not (style_match and body_match and script_match):
        raise RuntimeError(
            "The original HTML structure is missing its style, body, or script block."
        )

    return (
        style_match.group(1),
        body_match.group(1),
        script_match.group(1),
    )


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

    # Remove the original Claude database / downloads integration.
    backend_start = original_js.find(
        'const toastEl = document.getElementById("toast")'
    )

    render_start = original_js.find(
        "render(); update(); watchChapters();"
    )

    if backend_start < 0 or render_start < 0:
        raise RuntimeError(
            "Could not locate the original submission integration in the HTML."
        )

    core_js = (
        original_js[:backend_start]
        + original_js[render_start:]
    )

    core_js = core_js.replace(
        "render(); update(); watchChapters();",
        "if(!initialized){ render(); update(); watchChapters(); }",
    )

    # Scope DOM lookups to the V2 component root.
    core_js = re.sub(
        r'document\.getElementById\(("[^"]+")\)',
        lambda m:
            'root.querySelector("#' + m.group(1)[1:-1] + '")',
        core_js,
    )

    core_js = core_js.replace(
        "document.querySelectorAll(",
        "root.querySelectorAll(",
    )

    core_js = core_js.replace(
        "document.querySelector(",
        "root.querySelector(",
    )

    # Streamlit submission and download handling.
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

        statusEl.textContent =
            "Add the brand name at the top before sending.";

        root
            .querySelector('[data-key="client"]')
            .focus();

        return;
    }

    sendBtn.disabled = true;

    statusEl.textContent = "Sending…";

    setTriggerValue(
        "submit",
        payload()
    );
};


dlBtn.onclick = () => {

    const slug =
        (state.client || "answers")
        .replace(/[^\w\- ]+/g, "")
        .trim()
        .replace(/\s+/g, "-")
        || "answers";

    const url =
        URL.createObjectURL(
            new Blob(
                [toMarkdown()],
                { type: "text/markdown" }
            )
        );

    const a = document.createElement("a");

    a.href = url;

    a.download =
        "Brand-Questionnaire-" +
        slug +
        ".md";

    document.body.append(a);

    a.click();

    a.remove();

    setTimeout(
        () => URL.revokeObjectURL(url),
        1000
    );

    toast("Answers downloaded.");
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

    js = """
export default function(component) {

    const {
        parentElement,
        setTriggerValue,
        data
    } = component;

    const root = parentElement;

    const initialized =
        root.dataset.twiInitialized === "1";

    if (!initialized) {
        root.dataset.twiInitialized = "1";
    }

""" + core_js + """

}
"""

    # Preserve the original body markup.
    body = (
        '<div class="twi-streamlit-root">'
        + body
        + "</div>"
    )

    return body, css, js


@st.cache_resource(show_spinner=False)
def frontend() -> tuple[str, str, str]:

    return build_frontend(
        SOURCE.read_text(
            encoding="utf-8"
        )
    )


def send_email(payload: dict) -> None:

    smtp_user = st.secrets.get(
        "SMTP_USER",
        "hr@anotheridea.in",
    )

    smtp_pass = st.secrets["SMTP_PASS"]

    email_to = st.secrets.get(
        "EMAIL_TO",
        "gauravgandhi@anotheridea.in",
    )

    client = (
        payload.get("client")
        or "Untitled"
    )

    ref = (
        payload.get("ref")
        or "No reference"
    )

    subject = (
        f"The Way In submission | "
        f"{client} | {ref}"
    )

    markdown = (
        payload.get("markdown")
        or "No answers submitted."
    )

    plain = (
        "The Way In — Another Idea\n\n"
        f"Brand: {client}\n"
        f"Manager: {payload.get('manager') or '—'}\n"
        f"Reference: {ref}\n"
        f"Date: {payload.get('date') or '—'}\n"
        f"Submitted at: "
        f"{payload.get('submittedAt') or '—'}\n\n"
        f"{markdown}\n"
    )

    msg = EmailMessage()

    msg["From"] = smtp_user
    msg["To"] = email_to
    msg["Subject"] = subject

    msg.set_content(plain)

    smtp_host = st.secrets.get(
        "SMTP_HOST",
        "smtp.gmail.com",
    )

    smtp_port = int(
        st.secrets.get(
            "SMTP_PORT",
            465,
        )
    )

    with smtplib.SMTP_SSL(
        smtp_host,
        smtp_port,
        timeout=30,
    ) as smtp:

        smtp.login(
            smtp_user,
            smtp_pass,
        )

        smtp.send_message(msg)


HTML, CSS, JS = frontend()


component = st.components.v2.component(
    name="another_idea_the_way_in_v2",
    html=HTML,
    css=CSS,
    js=JS,
    isolate_styles=False,
)


send_status = st.session_state.pop(
    "twi_send_status",
    None,
)


result = component(
    key="the-way-in-questionnaire-v2",

    data={
        "send_status": send_status
    },

    width="stretch",

    height="content",

    on_submit_change=lambda: None,
)


if getattr(result, "submit", None):

    payload = result.submit

    try:

        send_email(payload)

        st.session_state[
            "twi_send_status"
        ] = "success"

    except Exception:

        st.session_state[
            "twi_send_status"
        ] = "error"

    st.rerun()

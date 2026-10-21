"""
הצ'אט: בוט שעונה על שאלות לקוחות מתוך אתר הפניקס. כל תשובה מגיעה עם הוכחה:
קישור לעמוד, וציטוטים מדויקים מהאתר שהקוד אימת מילה במילה (core/evidence.py).

הרצה (מתיקיית הפרויקט):
  streamlit run app.py
נפתח בדפדפן בכתובת http://localhost:8501

צריך: data/index/ (python ingest/index.py), ומפתחות GEMINI_API_KEY (חיפוש) ו-ANTHROPIC_API_KEY
(מודל השפה הראשי; בלעדיו - Gemini בלבד) בקובץ .env או ב-Secrets של Streamlit Cloud.
"""
import html
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import answer as answer_module  # noqa: E402
from core.answer import CONTACT_URL, answer_stream  # noqa: E402
from core.gaps import log_gap  # noqa: E402
from core.retriever import IndexNotReady, Retriever  # noqa: E402

MAX_CHARS = 500           # שאלה ארוכה מזה נחתכת בתיבת הקלט
RATE_PER_MINUTE = 6       # הגנה על מכסת המודל: שאלות לדקה לכל חלון דפדפן
RATE_PER_HOUR = 60

st.set_page_config(page_title="שירות לקוחות דיגיטלי", page_icon="🛡️", layout="centered",
                   initial_sidebar_state="collapsed")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700;800&family=Frank+Ruhl+Libre:wght@400;500&display=swap');
:root {
  --ink: #12304A; --muted: #5C6B78; --line: #DCE3E8; --paper: #FFFFFF; --surface: #F3F6F7;
  --teal: #0E7C7B; --teal-soft: #E3F2F1; --marker: #FFE58A; --ok: #1E7F4F; --wait: #A35F00;
}
html, body, .stApp, .stMarkdown, .stButton button, .stChatInput textarea, section[data-testid="stSidebar"],
[data-testid="stExpander"] summary {font-family: 'Assistant', 'Segoe UI', Arial, sans-serif;}
.stApp {background: var(--surface); color: var(--ink);}
.stApp, .stMarkdown, .stChatInput textarea, section[data-testid="stSidebar"], [data-testid="stExpander"] {direction: rtl; text-align: right;}
header[data-testid="stHeader"] {background: transparent;}
[data-testid="stToolbar"], [data-testid="stDecoration"], footer {display: none !important;}
.block-container {padding-top: 2.2rem; padding-bottom: 7rem; max-width: 760px;}

/* כותרת */
.top {display: flex; align-items: center; gap: .7rem; margin-bottom: 1.6rem;}
.top .seal {width: 2.6rem; height: 2.6rem; border-radius: 50%; background: var(--ink); color: #fff;
  display: grid; place-items: center; font-size: 1.25rem; flex: none;}
.top b {display: block; font-size: 1.15rem; font-weight: 800; letter-spacing: -.01em;}
.top span {color: var(--muted); font-size: .95rem;}

/* מסך פתיחה */
.welcome h1 {font-size: 2.6rem; line-height: 1.1; font-weight: 800; letter-spacing: -.02em; margin: .4rem 0 .6rem; color: var(--ink);}
.welcome p {font-size: 1.1rem; color: var(--muted); max-width: 34rem; margin: 0 0 1.4rem;}
.welcome .proof {display: inline-block; background: linear-gradient(transparent 55%, var(--marker) 55%); padding: 0 .15rem;}
.stButton button {border-radius: 999px; border: 1px solid var(--line); background: var(--paper); color: var(--ink);
  font-weight: 600; padding: .45rem 1rem; text-align: right;}
.stButton button:hover {border-color: var(--teal); color: var(--teal);}
.stButton button:focus-visible {outline: 3px solid var(--teal); outline-offset: 2px;}

/* הודעות */
[data-testid="stChatMessage"] {background: transparent; padding: .2rem 0; gap: 0;}
[data-testid^="stChatMessageAvatar"] {display: none;}
.msg-user {margin: 1.2rem 0 .4rem auto; margin-left: 0; max-width: 85%; width: fit-content; background: var(--ink); color: #fff;
  padding: .6rem 1rem; border-radius: 18px 18px 4px 18px; font-size: 1.05rem;}
.answer {background: var(--paper); border: 1px solid var(--line); border-radius: 16px; padding: 1.1rem 1.3rem .9rem;}
.answer-body {font-size: 1.07rem; line-height: 1.75;}
.answer-body p {margin: 0 0 .7rem;}
.answer-body ul, .answer-body ol {padding-right: 1.3rem; padding-left: 0; margin: 0 0 .7rem;}
.cursor {color: var(--teal); animation: blink 1s steps(1) infinite;}
@keyframes blink {50% {opacity: 0;}}
@media (prefers-reduced-motion: reduce) {.cursor {animation: none;}}

/* חותמת אמון */
.trust {display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .9rem; margin-top: .6rem; padding-top: .7rem;
  border-top: 1px dashed var(--line); font-size: .92rem; color: var(--muted);}
.stamp {display: inline-flex; align-items: center; gap: .35rem; font-weight: 700; color: var(--ok);}
.stamp.wait {color: var(--wait);}
.trust a {color: var(--teal); text-decoration: none; border-bottom: 1px solid #b9dcda;}
.trust a:hover {border-bottom-color: var(--teal);}

/* הראיות - הדבר שזוכרים */
[data-testid="stExpander"] {border: none; background: transparent; margin-top: -.2rem;}
[data-testid="stExpander"] details {border: none;}
[data-testid="stExpander"] summary {color: var(--teal); font-weight: 700; padding: .3rem 0;}
.slip {background: #FFFDF5; border: 1px solid #EFE6C4; border-right: 4px solid #E9C949; border-radius: 6px;
  padding: .75rem 1rem .6rem; margin: 0 0 .6rem;}
.slip q {font-family: 'Frank Ruhl Libre', Georgia, serif; font-size: 1.08rem; line-height: 1.8; quotes: "„" "”";}
.slip q mark {background: linear-gradient(transparent 40%, var(--marker) 40%); color: inherit; padding: 0 .1rem;}
.slip .from {display: block; margin-top: .35rem; font-size: .85rem; color: var(--muted);}
.slip .from a {color: var(--teal);}
.how {font-size: .85rem; color: var(--muted); margin: .2rem 0 0;}

/* לא נמצא / הבהרה */
.note {background: var(--paper); border: 1px solid var(--line); border-right: 4px solid var(--muted);
  border-radius: 12px; padding: .9rem 1.1rem; line-height: 1.7;}
.note b {display: block; margin-bottom: .2rem;}
.note a {color: var(--teal); font-weight: 600;}
.ask {border-right-color: var(--wait);}

.stChatInput {border-radius: 16px;}
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {background: var(--surface);}
[data-testid="stChatInput"] {background: var(--paper); border: 1px solid var(--line); box-shadow: 0 6px 24px rgba(18,48,74,.08);}
[data-testid="stChatInput"]:focus-within {border-color: var(--teal);}
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display: none;}
.about {margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--line); color: var(--muted); font-size: .92rem; line-height: 1.6;}
.st-key-actions {margin-top: 1rem;}
.more {margin: .9rem 0 .3rem; color: var(--muted); font-size: .92rem; font-weight: 600;}
.st-key-followups .stButton button {background: var(--teal-soft); border-color: #BFE0DD; color: var(--ink); font-size: .95rem;}
.st-key-followups .stButton button:hover {border-color: var(--teal); color: var(--teal);}
.st-key-actions .stButton button, .st-key-actions .stDownloadButton button {font-size: .9rem; padding: .3rem .9rem;}
.stDownloadButton button {border-radius: 999px; border: 1px solid var(--line); background: var(--paper); color: var(--ink); font-weight: 600;}
@media (max-width: 640px) {.welcome h1 {font-size: 2rem;} .block-container {padding-top: 1.2rem;}}
</style>""", unsafe_allow_html=True)

EXAMPLES = ["יש לי נזילה בבית, איך מגישים תביעה?",
            "הרכב עומד במוסך חודשיים, אפשר להשהות את הביטוח?",
            "מה כולל ביטוח לחתול?",
            "אפשר לקחת הלוואה כנגד קרן השתלמות?"]


@st.cache_resource(max_entries=1)
def _load_bot(built_at):
    """נטען פעם אחת לכל השרת: האינדקס ומטמון התשובות (משותף, רק לשאלה ראשונה בשיחה - בלי היסטוריה).
    המפתח הוא זמן בניית האינדקס: אחרי רענון מעמוד המנהל נטען האינדקס החדש (ומטמון התשובות מתאפס)."""
    answer_module._retriever = Retriever()
    return answer_module._retriever.manifest, {}


def load_bot():
    try:
        built_at = json.loads((ROOT / "data" / "index" / "manifest.json").read_text(encoding="utf-8"))["built_at"]
    except Exception:
        built_at = None
    return _load_bot(built_at)


def normalize(question):
    return re.sub(r"\s+", " ", re.sub(r"[?!.,״\"']", "", question)).strip()


def _md(text):
    """טקסט מהמודל מוצג כ-markdown, אבל בלי HTML: תגיות שהמודל כתב מוצגות כטקסט ולא רצות."""
    return html.escape(text, quote=False)


def trust_html(msg):
    sources = msg.get("sources") or []
    links = " ".join(f'<a href="{html.escape(s["url"])}" target="_blank" rel="noopener">{html.escape(s["title"])}</a>'
                     for s in sources)
    trust = msg.get("trust") or {}
    if trust.get("quotes"):
        stamp = '<span class="stamp">✓ אומת מול האתר</span>'
    else:
        stamp = '<span class="stamp">✓ מבוסס על עמוד באתר</span>'
    return f'<div class="trust">{stamp}<span>מקור: {links}</span></div>'


def evidence_html(evidence):
    slips = []
    for e in evidence:
        slips.append(f'<div class="slip"><q><mark>{html.escape(e["quote"])}</mark></q>'
                     f'<span class="from">מתוך: <a href="{html.escape(e["url"])}" target="_blank" rel="noopener">'
                     f'{html.escape(e["title"])}</a></span></div>')
    slips.append('<p class="how">כל ציטוט נבדק אוטומטית מילה במילה מול הטקסט באתר, וכל מספר בתשובה '
                 '(סכום, אחוז, טלפון) מופיע באתר. תשובה שלא עוברת את הבדיקה לא מוצגת.</p>')
    return "".join(slips)


def show(msg):
    status = msg.get("status")
    if msg["role"] == "user":
        st.markdown(f'<div class="msg-user">{html.escape(msg["text"])}</div>', unsafe_allow_html=True)
        return
    if status in ("not_found", "unavailable", "personal"):
        title = {"not_found": "אין מספיק מידע באתר", "unavailable": "השירות לא זמין כרגע",
                 "personal": "את זה בודקים בשירות הלקוחות"}[status]
        st.markdown(f'<div class="note"><b>{title}</b>{html.escape(msg["text"])}<br>'
                    f'<a href="{CONTACT_URL}" target="_blank" rel="noopener">לכל הדרכים ליצור קשר עם הפניקס</a></div>',
                    unsafe_allow_html=True)
        return
    if status == "clarify":
        st.markdown(f'<div class="note ask"><b>שאלה קטנה לפני שאני עונה</b>{html.escape(msg["text"])}</div>',
                    unsafe_allow_html=True)
        return
    trust = trust_html(msg) if status == "answer" and msg.get("sources") else ""
    st.markdown(f'<div class="answer"><div class="answer-body">\n\n{_md(msg["text"])}\n\n</div>{trust}</div>',
                unsafe_allow_html=True)
    if status == "answer" and msg.get("evidence"):
        with st.expander(f"הראו לי איפה זה כתוב ({len(msg['evidence'])})"):
            st.markdown(evidence_html(msg["evidence"]), unsafe_allow_html=True)


def transcript(messages):
    """השיחה כטקסט להורדה: שאלות, תשובות, מקורות וציטוטים."""
    lines = [f"שיחה עם הבוט של אתר הפניקס - {datetime.now():%d/%m/%Y %H:%M}", ""]
    for m in messages:
        lines.append(("לקוח: " if m["role"] == "user" else "בוט: ") + m["text"])
        for src in m.get("sources") or []:
            lines.append(f"   מקור: {src['title']} - {src['url']}")
        for e in m.get("evidence") or []:
            lines.append(f"   ציטוט מהאתר: \"{e['quote']}\"")
        lines.append("")
    return "\n".join(lines)


def rate_limited():
    """True אם בחלון הזה נשאלו יותר מדי שאלות לאחרונה (הגנה מפני ניצול המפתח)."""
    now = time.time()
    stamps = [t for t in st.session_state.get("asked", []) if now - t < 3600]
    st.session_state.asked = stamps
    if sum(now - t < 60 for t in stamps) >= RATE_PER_MINUTE or len(stamps) >= RATE_PER_HOUR:
        return True
    stamps.append(now)
    return False


def respond(question, history, manifest, cache):
    """מציג את התשובה תוך כדי כתיבה, ומחזיר את ההודעה הסופית לשמירה בהיסטוריה."""
    key = (manifest["built_at"], normalize(question))
    if not history and key in cache:  # שאלה ראשונה שכבר נשאלה - מיד, בלי לפנות למודל
        result = cache[key]
    else:
        progress, box = st.empty(), st.empty()
        result = None
        for kind, value in answer_stream(question, history=history):
            if kind == "status":
                progress.caption(value)
            elif kind == "text":
                progress.empty()
                box.markdown(f'<div class="answer"><div class="answer-body">\n\n{_md(value)} '
                             f'<span class="cursor">▌</span>\n\n</div></div>', unsafe_allow_html=True)
            else:
                result = value
        progress.empty()
        box.empty()  # הטקסט הסופי מוצג מחדש (ואם הבדיקה נכשלה - מוחלף ב"לא מצאתי")
        if not history and result["status"] in ("answer", "not_found"):
            cache[key] = result
        if result["status"] == "not_found":
            log_gap(question, result.get("search_query"), result.get("reason"))
    msg = {"role": "assistant", "text": result["answer"], "status": result["status"],
           "sources": result.get("sources", []), "evidence": result.get("evidence", []),
           "trust": result.get("trust"), "followups": result.get("followups", [])}
    show(msg)
    return msg


# ---------- טעינה ----------
try:
    manifest, cache = load_bot()
except IndexNotReady as e:
    st.error(f"הבוט לא מוכן: {e}")
    st.stop()

# ---------- השיחה ----------
st.markdown('<div class="top"><div class="seal">🛡️</div><div><b>שירות לקוחות דיגיטלי</b>'
            '<span>תשובות מתוך אתר הפניקס</span></div></div>', unsafe_allow_html=True)
if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    st.markdown('<div class="welcome"><h1>מה תרצו לברר?</h1>'
                '<p>ביטוח, תביעות, פנסיה, חיסכון והלוואות. כל תשובה מגיעה עם '
                '<span class="proof">המשפט המדויק מהאתר שמוכיח אותה</span>.</p></div>', unsafe_allow_html=True)
    for ex in EXAMPLES:
        if st.button(ex, key=ex):
            st.session_state.pending = ex
            st.rerun()
    crawled = manifest.get("newest_crawl") or ""
    try:
        age = f" (לפני {(date.today() - datetime.fromisoformat(crawled).date()).days} ימים)"
    except ValueError:
        age = ""
    st.markdown(f'<div class="about">הבוט מסביר מה כתוב באתר fnx.co.il. הוא לא נותן ייעוץ אישי ואין לו גישה '
                f'לפוליסה שלכם - את אלה בודקים בשירות הלקוחות. המידע נאסף מהאתר ב-{html.escape(crawled)}{age}, '
                f'{manifest["pages"]} עמודים. השיחה לא נשמרת אחרי סגירת החלון.</div>', unsafe_allow_html=True)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        show(msg)

last = st.session_state.messages[-1] if st.session_state.messages else None
if last and last["role"] == "assistant" and last.get("followups"):
    st.markdown('<div class="more">רוצים לדעת עוד?</div>', unsafe_allow_html=True)
    with st.container(key="followups", horizontal=True):
        for i, fq in enumerate(last["followups"]):
            if st.button(fq, key=f"fu{len(st.session_state.messages)}_{i}"):
                st.session_state.pending = fq
                st.rerun()

if st.session_state.messages:
    with st.container(key="actions", horizontal=True):
        if st.button("שיחה חדשה"):
            st.session_state.messages = []
            st.rerun()
        st.download_button("הורדת השיחה", transcript(st.session_state.messages).encode("utf-8"),
                           file_name="fnx-bot-conversation.txt", mime="text/plain")

question = st.chat_input("כתבו שאלה...", max_chars=MAX_CHARS) or st.session_state.pop("pending", None)
if question:
    question = question.strip()[:MAX_CHARS]
    if rate_limited():
        st.toast("נשאלו הרבה שאלות בזמן קצר. אפשר לנסות שוב בעוד דקה.")
    elif question:
        history = [{"role": m["role"], "text": m["text"]} for m in st.session_state.messages]
        st.session_state.messages.append({"role": "user", "text": question})
        with st.chat_message("user"):
            show(st.session_state.messages[-1])
        with st.chat_message("assistant"):
            st.session_state.messages.append(respond(question, history, manifest, cache))
        st.rerun()  # מצייר מחדש מההיסטוריה, כדי שגם כפתור ההורדה יכלול את התשובה האחרונה

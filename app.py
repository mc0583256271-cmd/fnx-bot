"""
הצ'אט: בוט שעונה על שאלות לקוחות מתוך אתר הפניקס, עם קישור למקור בכל תשובה.

הרצה (מתיקיית הפרויקט):
  streamlit run app.py
נפתח בדפדפן בכתובת http://localhost:8501

צריך: data/index/ (python ingest/index.py), ו-.env עם GEMINI_API_KEY (חיפוש)
ו-ANTHROPIC_API_KEY (מודל השפה הראשי; בלעדיו - Gemini בלבד).
"""
import html
import re
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import answer as answer_module  # noqa: E402
from core.answer import CONTACT_URL, answer_stream  # noqa: E402
from core.retriever import IndexNotReady, Retriever  # noqa: E402

st.set_page_config(page_title="שירות לקוחות דיגיטלי", page_icon="💬", layout="centered")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&display=swap');
html, body, .stApp, .stMarkdown, .stChatMessage, .stButton button, .stChatInput textarea, section[data-testid="stSidebar"] {
  font-family: 'Heebo', 'Segoe UI', Arial, sans-serif; }
.stApp, .stChatMessage, .stMarkdown, .stChatInput textarea, section[data-testid="stSidebar"] {direction: rtl; text-align: right;}
.stChatMessage ul, .stChatMessage ol {padding-right: 1.3rem; padding-left: 0;}
.hero {text-align: center; margin: 0.5rem 0 1.2rem;}
.hero h1 {font-size: 1.9rem; font-weight: 700; margin-bottom: 0.2rem;}
.hero p {color: #5b6b7c; margin: 0;}
.sources {margin-top: 0.6rem; padding-top: 0.5rem; border-top: 1px solid #e3e8ef; font-size: 0.88rem; color: #5b6b7c;}
.sources a {display: inline-block; margin: 0.15rem 0 0.15rem 0.35rem; padding: 0.15rem 0.6rem; border-radius: 999px;
  background: #eef4fb; color: #0b5cad; text-decoration: none; border: 1px solid #d6e4f5;}
.sources a:hover {background: #dbe9f8;}
.note {background: #f6f8fb; border: 1px solid #e3e8ef; border-radius: 10px; padding: 0.7rem 0.9rem;}
.note a {color: #0b5cad;}
.cursor {color: #0b5cad;}
</style>""", unsafe_allow_html=True)

EXAMPLES = ["יש לי נזילה בבית, איך מגישים תביעה?",
            "הרכב עומד במוסך חודשיים, אפשר להשהות את הביטוח?",
            "אני בחו\"ל ורוצה להישאר עוד שבוע, אפשר להאריך את הביטוח?"]
AVATARS = {"user": "🙂", "assistant": "💬"}


@st.cache_resource
def load_bot():
    """נטען פעם אחת לכל השרת: האינדקס (2,405 פסקאות) ומטמון התשובות."""
    answer_module._retriever = Retriever()
    return answer_module._retriever.manifest, {}


def normalize(question):
    return re.sub(r"\s+", " ", re.sub(r"[?!.,״\"']", "", question)).strip()


def sources_html(sources):
    links = "".join(f'<a href="{html.escape(s["url"])}" target="_blank">{html.escape(s["title"])}</a>'
                    for s in sources)
    return f'<div class="sources">מקור: {links}</div>'


def show(msg):
    status = msg.get("status")
    if status in ("not_found", "unavailable", "personal"):
        st.markdown(f'<div class="note">{html.escape(msg["text"])}<br>'
                    f'<a href="{CONTACT_URL}" target="_blank">לכל הדרכים ליצור קשר עם הפניקס</a></div>',
                    unsafe_allow_html=True)
        return
    st.markdown(msg["text"])
    if status == "answer" and msg.get("sources"):
        st.markdown(sources_html(msg["sources"]), unsafe_allow_html=True)


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
                box.markdown(value + ' <span class="cursor">▌</span>', unsafe_allow_html=True)
            else:
                result = value
        progress.empty()
        box.empty()  # הטקסט הסופי מוצג מחדש (ואם התברר שאין מקור - מוחלף ב"לא מצאתי")
        if not history and result["status"] in ("answer", "not_found"):
            cache[key] = result
    msg = {"role": "assistant", "text": result["answer"], "status": result["status"],
           "sources": result.get("sources", [])}
    show(msg)
    return msg


# ---------- טעינה ----------
try:
    manifest, cache = load_bot()
except IndexNotReady as e:
    st.error(f"הבוט לא מוכן: {e}")
    st.stop()

# ---------- צד ----------
with st.sidebar:
    st.subheader("על הבוט")
    st.write("עונה על שאלות רק מתוך המידע שבאתר fnx.co.il, ומצרף לכל תשובה קישור לעמוד שממנו היא נלקחה. "
             "כשהמידע לא מופיע באתר - הבוט אומר זאת ומפנה לשירות הלקוחות.")
    crawled = manifest.get("newest_crawl") or ""
    try:
        age = (date.today() - datetime.fromisoformat(crawled).date()).days
        st.caption(f"המידע נאסף מהאתר: {crawled} (לפני {age} ימים)")
    except ValueError:
        st.caption(f"המידע נאסף מהאתר: {crawled}")
    st.caption(f"{manifest['pages']} עמודים · {manifest['chunks']} פסקאות")
    if st.button("שיחה חדשה", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("הבוט מסביר מה כתוב באתר. הוא לא נותן ייעוץ אישי ואין לו גישה לפוליסה שלך - "
               "את אלה בודקים בשירות הלקוחות.")

# ---------- השיחה ----------
st.markdown('<div class="hero"><h1>איך אפשר לעזור?</h1>'
            '<p>שאלו על ביטוח, תביעות, פנסיה, חיסכון והלוואות - התשובות מתוך אתר הפניקס</p></div>',
            unsafe_allow_html=True)
if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    for col, ex in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        if col.button(ex, use_container_width=True):
            st.session_state.pending = ex
            st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
        show(msg)

question = st.chat_input("כתבו שאלה...") or st.session_state.pop("pending", None)
if question:
    history = [{"role": m["role"], "text": m["text"]} for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "text": question})
    with st.chat_message("user", avatar=AVATARS["user"]):
        st.markdown(question)
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        st.session_state.messages.append(respond(question, history, manifest, cache))

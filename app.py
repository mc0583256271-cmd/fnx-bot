"""
הצ'אט: בוט שעונה על שאלות לקוחות מתוך אתר הפניקס, עם קישור למקור בכל תשובה.

הרצה (מתיקיית הפרויקט):
  streamlit run app.py
נפתח בדפדפן בכתובת http://localhost:8501

צריך: data/index/ (python ingest/index.py), ו-.env עם GEMINI_API_KEY (חיפוש)
ו-ANTHROPIC_API_KEY (מודל השפה הראשי; בלעדיו - Gemini בלבד).
"""
import re
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import answer as answer_module  # noqa: E402
from core.answer import CONTACT_URL, answer  # noqa: E402
from core.retriever import IndexNotReady, Retriever  # noqa: E402

st.set_page_config(page_title="הבוט של הפניקס", page_icon="💬", layout="centered")
st.markdown("""<style>
.stApp, .stChatMessage, .stMarkdown, .stChatInput textarea, section[data-testid="stSidebar"] {direction: rtl; text-align: right;}
.stChatMessage ul, .stChatMessage ol {padding-right: 1.2rem; padding-left: 0;}
</style>""", unsafe_allow_html=True)

EXAMPLES = ["יש לי נזילה בבית, איך מגישים תביעה?",
            "הרכב עומד במוסך חודשיים, אפשר להשהות את הביטוח?",
            "אני כבר בחו\"ל ורוצה להישאר עוד שבוע, אפשר להאריך?"]


@st.cache_resource
def load_bot():
    """נטען פעם אחת לכל השרת: האינדקס (2,405 פסקאות) ומטמון התשובות."""
    answer_module._retriever = Retriever()
    return answer_module._retriever.manifest, {}


def normalize(question):
    return re.sub(r"\s+", " ", re.sub(r"[?!.,״\"']", "", question)).strip()


def ask(question, history, manifest, cache):
    """שאלה ראשונה בשיחה שכבר נשאלה (אותו אינדקס) - מהמטמון, מיד. שאלת המשך תלויה בשיחה - לא נשמרת."""
    key = (manifest["built_at"], normalize(question))
    if not history and key in cache:
        return dict(cache[key], cached=True)
    result = answer(question, history=history)
    if not history and result["status"] in ("answer", "not_found"):
        cache[key] = result
    return result


def show(msg):
    st.markdown(msg["text"])
    if msg.get("status") == "answer" and msg.get("sources"):
        links = " · ".join(f"[{s['title']}]({s['url']})" for s in msg["sources"])
        st.markdown(f"**מקור:** {links}")
    elif msg.get("status") in ("not_found", "unavailable"):
        st.markdown(f"[לכל הדרכים ליצור קשר עם הפניקס]({CONTACT_URL})")


# ---------- טעינה ----------
try:
    manifest, cache = load_bot()
except IndexNotReady as e:
    st.error(f"הבוט לא מוכן: {e}")
    st.stop()

# ---------- צד: מתי עודכן המידע ----------
with st.sidebar:
    st.header("הבוט של הפניקס")
    st.write("עונה על שאלות רק מתוך המידע שבאתר fnx.co.il, עם קישור למקור.")
    crawled = manifest.get("newest_crawl") or ""
    try:
        age = (date.today() - datetime.fromisoformat(crawled).date()).days
        st.caption(f"המידע נאסף מהאתר: {crawled} (לפני {age} ימים)")
    except ValueError:
        st.caption(f"המידע נאסף מהאתר: {crawled}")
    st.caption(f"{manifest['pages']} עמודים · {manifest['chunks']} פסקאות")
    if st.button("שיחה חדשה"):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("הבוט מסביר מה כתוב באתר. הוא לא נותן ייעוץ אישי ואין לו גישה לפוליסה שלך - "
               "את אלה בודקים בשירות הלקוחות.")

# ---------- השיחה ----------
st.title("איך אפשר לעזור?")
if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    st.caption("לדוגמה:")
    for ex in EXAMPLES:
        if st.button(ex):
            st.session_state.pending = ex
            st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        show(msg)

question = st.chat_input("שאלו על ביטוח, תביעות, פנסיה, חיסכון...") or st.session_state.pop("pending", None)
if question:
    history = [{"role": m["role"], "text": m["text"]} for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("מחפש באתר הפניקס..."):
            result = ask(question, history, manifest, cache)
        msg = {"role": "assistant", "text": result["answer"], "status": result["status"],
               "sources": result.get("sources", [])}
        show(msg)
    st.session_state.messages.append(msg)

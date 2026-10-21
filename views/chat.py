"""
הצ'אט: בוט שעונה על שאלות לקוחות מתוך אתר הפניקס. כל תשובה מגיעה עם הוכחה:
קישור לעמוד, וציטוטים מדויקים מהאתר שהקוד אימת מילה במילה (core/evidence.py).

נטען מ-app.py (הניתוב). הרצה (מתיקיית הפרויקט):
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import answer as answer_module  # noqa: E402
from core.answer import CONTACT_URL, answer_stream  # noqa: E402
from core.gaps import log_gap  # noqa: E402
from core.retriever import IndexNotReady, Retriever  # noqa: E402

MAX_CHARS = 500           # שאלה ארוכה מזה נחתכת בתיבת הקלט
RATE_PER_MINUTE = 6       # הגנה על מכסת המודל: שאלות לדקה לכל חלון דפדפן
RATE_PER_HOUR = 60

st.markdown("""<style>
/* שפת העיצוב של אתר הפניקס: כחול כהה #111C3F, כתום #FF4E31, רקע #F5F6FA, כפתורים מעוגלים, כרטיסים לבנים עם צל רך.
   הגופן באתר (Ploni) מסחרי - Rubik הוא הקרוב ביותר שזמין בחינם. */
@import url('https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700&display=swap');
:root {
  --blue: #111C3F; --orange: #FF4E31; --orange-soft: #FFF1EE; --gray: #6B6E77; --line: #E0DFDF;
  --paper: #FFFFFF; --surface: #F5F6FA; --sky: #F2FAFE; --sky-line: #D6EEF9; --green: #1F9C7E;
  --shadow: 0 2px 15px rgba(0, 0, 0, .08);
}
html, body, .stApp, .stMarkdown, .stButton button, .stDownloadButton button, .stChatInput textarea,
[data-testid="stExpander"] summary {font-family: 'Rubik', 'Segoe UI', Arial, sans-serif;}
.stApp {background: var(--surface); color: var(--blue);}
.stApp, .stMarkdown, .stChatInput textarea, [data-testid="stExpander"] {direction: rtl; text-align: right;}
header[data-testid="stHeader"] {display: none;}
[data-testid="stElementContainer"]:has(.topbar) {position: sticky; top: .5rem; z-index: 50;}
[data-testid="stToolbar"], [data-testid="stDecoration"], footer, section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] {display: none !important;}
.block-container {padding-top: 0; padding-bottom: 7rem; max-width: 780px;}

/* פס עליון - כמו הכותרת באתר */
.block-container {padding-top: 1.2rem;}
.topbar {display: flex; align-items: center; justify-content: space-between; gap: 1rem; background: var(--paper);
  margin: 0 0 1.8rem; padding: .8rem 1.1rem; border-radius: 14px; box-shadow: var(--shadow); border-bottom: 3px solid var(--orange);}
.brand {display: flex; align-items: center; gap: .65rem;}
.brand .dot {width: 2.4rem; height: 2.4rem; border-radius: 50%; background: var(--orange); color: #fff;
  display: grid; place-items: center; font-size: 1.15rem; flex: none;}
.brand b {display: block; font-size: 1.12rem; font-weight: 700;}
.brand span {display: block; color: var(--gray); font-size: .85rem;}
.topbar a {color: var(--blue); font-size: .9rem; font-weight: 500; text-decoration: none; border-bottom: 2px solid var(--orange);}

/* מסך פתיחה */
.welcome h1 {font-size: 2.3rem; line-height: 1.15; font-weight: 700; margin: .6rem 0 .5rem; color: var(--blue);}
.welcome p {font-size: 1.08rem; color: var(--gray); max-width: 36rem; margin: 0 0 1.3rem; line-height: 1.6;}
.stButton button {border-radius: 22px; border: 1px solid var(--line); background: var(--paper); color: var(--blue);
  font-weight: 500; padding: .5rem 1.1rem; text-align: right; box-shadow: none;}
.stButton button:hover {border-color: var(--orange); color: var(--orange); background: var(--paper);}
.stButton button:focus-visible {outline: 3px solid var(--orange); outline-offset: 2px;}
.st-key-examples [data-testid="stElementContainer"], .st-key-examples .stButton {width: 100% !important;}
.st-key-examples .stButton button {width: 100%; min-height: 4.4rem; border-radius: 10px; box-shadow: var(--shadow);
  border-color: transparent; font-size: 1rem; justify-content: flex-start; white-space: normal; line-height: 1.4;}
.st-key-examples .stButton button p {white-space: normal; overflow: visible; text-overflow: clip; text-align: right;}
.st-key-examples .stButton button:hover {border-color: var(--orange);}

/* הודעות */
[data-testid="stChatMessage"] {background: transparent; padding: .2rem 0; gap: 0;}
[data-testid^="stChatMessageAvatar"] {display: none;}
.msg-user {margin: 1.3rem 0 .5rem auto; margin-left: 0; max-width: 85%; width: fit-content; background: var(--blue); color: #fff;
  padding: .65rem 1.1rem; border-radius: 20px 20px 4px 20px; font-size: 1.04rem;}
.answer {background: var(--paper); border-radius: 12px; padding: 1.1rem 1.3rem .9rem; box-shadow: var(--shadow);}
.answer-body {font-size: 1.06rem; line-height: 1.75;}
.answer-body p {margin: 0 0 .6rem;}
.answer-body ul, .answer-body ol {padding-right: 1.3rem; padding-left: 0; margin: 0 0 .6rem;}
.cursor {color: var(--orange); animation: blink 1s steps(1) infinite;}
@keyframes blink {50% {opacity: 0;}}
@media (prefers-reduced-motion: reduce) {.cursor {animation: none;}}

/* מקור ואימות */
.trust {display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .8rem; margin-top: .5rem; padding-top: .7rem;
  border-top: 1px solid #EEEFF2; font-size: .9rem; color: var(--gray);}
.stamp {display: inline-flex; align-items: center; gap: .3rem; font-weight: 600; color: var(--green);}
.trust a {color: var(--blue); text-decoration: none; background: var(--sky); border: 1px solid var(--sky-line);
  border-radius: 22px; padding: .12rem .7rem;}
.trust a:hover {border-color: var(--blue);}

/* הראיות: הציטוטים מהאתר, מסומנים כמו בטוש */
[data-testid="stExpander"] {border: none; background: transparent; margin-top: -.1rem;}
[data-testid="stExpander"] details {border: none;}
[data-testid="stExpander"] summary {color: var(--blue); font-weight: 500; font-size: .92rem; padding: .3rem 0;}
.slip {background: var(--paper); border-right: 3px solid var(--orange); border-radius: 6px; box-shadow: var(--shadow);
  padding: .75rem 1rem .6rem; margin: 0 0 .6rem;}
.slip q {font-size: 1.02rem; line-height: 1.8; quotes: "„" "”";}
.slip q mark {background: linear-gradient(transparent 45%, #FFD9CF 45%); color: inherit; padding: 0 .1rem;}
.slip .from {display: block; margin-top: .3rem; font-size: .84rem; color: var(--gray);}
.slip .from a {color: var(--blue);}
.how {font-size: .84rem; color: var(--gray); margin: .2rem 0 0;}

/* לא נמצא / הבהרה */
.note {background: var(--paper); border-radius: 12px; box-shadow: var(--shadow); border-right: 4px solid var(--gray);
  padding: .95rem 1.2rem; line-height: 1.7;}
.note b {display: block; margin-bottom: .15rem;}
.note a {color: var(--orange); font-weight: 600;}
.ask {border-right-color: var(--orange);}

/* שאלות המשך ופעולות */
.more {margin: 1rem 0 .35rem; color: var(--gray); font-size: .9rem;}
.st-key-followups .stButton button {background: var(--orange-soft); border-color: #FFD4CB; font-size: .95rem;}
.st-key-followups .stButton button:hover {border-color: var(--orange);}
.st-key-actions {margin-top: 1rem;}
.st-key-actions .stButton button, .stDownloadButton button {font-size: .88rem; padding: .3rem .9rem; border-radius: 22px;
  border: 1px solid var(--line); background: transparent; color: var(--gray); font-weight: 500;}
.about {margin-top: 2.2rem; color: var(--gray); font-size: .88rem; line-height: 1.6;}

/* תיבת הכתיבה */
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {background: var(--surface);}
[data-testid="stChatInput"] {background: var(--paper); border: 1px solid var(--line); border-radius: 26px; box-shadow: var(--shadow);}
[data-testid="stChatInput"]:focus-within {border-color: var(--blue);}
[data-testid="stChatInputSubmitButton"] {background: var(--orange) !important; color: #fff !important; border-radius: 50% !important;}
.topbar a {white-space: nowrap;}
@media (max-width: 640px) {.welcome h1 {font-size: 1.8rem;} .brand span {display: none;} .topbar {padding: .55rem .8rem;}
  .brand b {font-size: .98rem;} .brand .dot {width: 2rem; height: 2rem; font-size: 1rem;} .topbar a {font-size: .82rem;}}
</style>""", unsafe_allow_html=True)

EXAMPLES = [("🏠", "יש לי נזילה בבית, איך מגישים תביעה?"),
            ("🚗", "הרכב עומד במוסך חודשיים, אפשר להשהות את הביטוח?"),
            ("🐾", "מה כולל ביטוח לחתול?"),
            ("💰", "אפשר לקחת הלוואה כנגד קרן השתלמות?")]


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
st.markdown(f'<div class="topbar"><div class="brand"><div class="dot">💬</div><div><b>העוזר הדיגיטלי של הפניקס</b>'
            f'<span>תשובות מתוך אתר fnx.co.il</span></div></div>'
            f'<a href="{CONTACT_URL}" target="_blank" rel="noopener">דברו עם נציג</a></div>', unsafe_allow_html=True)
if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    st.markdown('<div class="welcome"><h1>שלום, איך אפשר לעזור?</h1>'
                '<p>אפשר לשאול אותי על ביטוח, תביעות, פנסיה וחיסכון. אני עונה לפי המידע שבאתר הפניקס, '
                'ולכל תשובה מצרף קישור לעמוד שממנו היא נלקחה.</p></div>', unsafe_allow_html=True)
    with st.container(key="examples"):
        cols = st.columns(2)
        for i, (icon, ex) in enumerate(EXAMPLES):
            if cols[i % 2].button(f"{icon}  {ex}", key=f"ex{i}"):
                st.session_state.pending = ex
                st.rerun()
    crawled = manifest.get("newest_crawl") or ""
    try:
        age = f" (לפני {(date.today() - datetime.fromisoformat(crawled).date()).days} ימים)"
    except ValueError:
        age = ""
    st.markdown(f'<div class="about">הבוט מסביר מה כתוב באתר. הוא לא נותן ייעוץ אישי ואין לו גישה לפוליסה שלכם - '
                f'את אלה בודקים בשירות הלקוחות. המידע נאסף מהאתר ב-{html.escape(crawled)}{age}. '
                f'השיחה לא נשמרת אחרי סגירת החלון.</div>', unsafe_allow_html=True)

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

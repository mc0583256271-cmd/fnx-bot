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
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import answer as answer_module  # noqa: E402
from core.answer import CONTACT_URL, answer_stream  # noqa: E402
from core.gaps import log_feedback, log_gap  # noqa: E402
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
  margin: 0 0 1.2rem; padding: .8rem 1.1rem; border-radius: 14px; box-shadow: var(--shadow); border-bottom: 3px solid var(--orange);}
.brand {display: flex; align-items: center; gap: .65rem;}
.brand .dot {width: 2.4rem; height: 2.4rem; border-radius: 50%; background: var(--orange); color: #fff;
  display: grid; place-items: center; font-size: 1.15rem; flex: none;}
.brand b {display: block; font-size: 1.12rem; font-weight: 700;}
.brand span {display: block; color: var(--gray); font-size: .85rem;}
.topbar a {color: var(--blue); font-size: .9rem; font-weight: 500; text-decoration: none; border-bottom: 2px solid var(--orange);}

/* מסך פתיחה */
.welcome h1 {font-size: 2.1rem; line-height: 1.15; font-weight: 700; margin: 0 0 .4rem; color: var(--blue);}
.welcome p {font-size: 1.02rem; color: var(--gray); max-width: 36rem; margin: 0 0 .4rem; line-height: 1.55;}
.stButton button {border-radius: 22px; border: 1px solid var(--line); background: var(--paper); color: var(--blue);
  font-weight: 500; padding: .5rem 1.1rem; text-align: right; box-shadow: none;}
.stButton button:hover {border-color: var(--orange); color: var(--orange); background: var(--paper);}
.stButton button:focus-visible {outline: 3px solid var(--orange); outline-offset: 2px;}
.label {margin: .8rem 0 .4rem; color: var(--gray); font-size: .9rem; font-weight: 500;}
/* אריחי נושאים - כמו אייקוני המוצרים באתר */
.st-key-topics .stButton button {min-height: 4.6rem; border-radius: 14px; border-color: transparent; box-shadow: var(--shadow);
  justify-content: center; text-align: center; font-weight: 500; transition: transform .15s ease, box-shadow .15s ease;}
.st-key-topics .stButton button p {text-align: center; font-size: 1rem; margin: 0; line-height: 1.3;
  white-space: normal; overflow: visible; text-overflow: clip;}
.st-key-topics .stButton button p:first-child {font-size: 1.7rem;}
.st-key-topics .stButton button:hover {transform: translateY(-3px); box-shadow: 0 8px 22px rgba(17,28,63,.13);
  border-color: var(--orange); color: var(--blue);}
@media (max-width: 640px) {
  .st-key-topics [data-testid="stHorizontalBlock"] {flex-direction: row !important; flex-wrap: nowrap !important; gap: .5rem;}
  .st-key-topics [data-testid="stColumn"] {min-width: 0 !important; width: auto !important; flex: 1 1 0 !important;}
  .st-key-topics .stButton button {min-height: 4.6rem; padding: .4rem .3rem;}
  .st-key-topics .stButton button p {font-size: .85rem;}}
.st-key-examples {flex-wrap: wrap; gap: .5rem;}
.st-key-examples .stButton button {font-size: .93rem; padding: .4rem .95rem; background: var(--paper);}
@media (prefers-reduced-motion: reduce) {.st-key-topics .stButton button {transition: none;}
  .st-key-topics .stButton button:hover {transform: none;}}
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

/* מי מדבר: נקודה כתומה קטנה ו"העוזר הדיגיטלי" מעל כל תשובה */
.who {display: flex; align-items: center; gap: .4rem; color: var(--gray); font-size: .8rem; margin: 1rem 0 .35rem;}
.who i {width: .55rem; height: .55rem; border-radius: 50%; background: var(--orange); display: inline-block;}
/* תשובה חדשה נכנסת בעדינות (פעם אחת, רק התשובה שנכתבה עכשיו) */
.fresh {animation: rise .35s ease-out both;}
@keyframes rise {from {opacity: 0; transform: translateY(6px);}}
@media (prefers-reduced-motion: reduce) {.fresh {animation: none;}}
/* "עזרתי?" 👍 👎 */
[class*="st-key-fbrow"] {align-items: center; gap: .35rem; margin: .25rem 0 0; opacity: .75;}
[class*="st-key-fbrow"]:hover {opacity: 1;}
.fbq {color: var(--gray); font-size: .82rem;}
[class*="st-key-fbrow"] [data-testid="stMarkdownContainer"] p {margin: 0;}

/* "הבוט כותב..." - שלוש נקודות כמו באפליקציות צ'אט */
.typing {display: inline-flex; align-items: center; gap: .3rem; background: var(--paper); border-radius: 20px;
  padding: .55rem 1rem; box-shadow: var(--shadow); color: var(--gray); font-size: .92rem;}
.typing span {width: .45rem; height: .45rem; border-radius: 50%; background: var(--orange); opacity: .35;
  animation: dot 1.2s infinite;}
.typing span:nth-child(2) {animation-delay: .2s;} .typing span:nth-child(3) {animation-delay: .4s; margin-left: .4rem;}
@keyframes dot {30% {opacity: 1; transform: translateY(-2px);}}
@media (prefers-reduced-motion: reduce) {.typing span {animation: none; opacity: .8;}}

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
.about {margin-top: 1.1rem; color: var(--gray); font-size: .84rem; line-height: 1.55;}

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
    return "".join(slips)


def show(msg, fresh=False):
    status = msg.get("status")
    if msg["role"] == "user":
        st.markdown(f'<div class="msg-user">{html.escape(msg["text"])}</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="who{" fresh" if fresh else ""}"><i></i>העוזר הדיגיטלי</div>', unsafe_allow_html=True)
    if status in ("not_found", "unavailable", "personal"):
        title = {"not_found": "אין מספיק מידע באתר", "unavailable": "השירות לא זמין כרגע",
                 "personal": "את זה בודקים בשירות הלקוחות"}[status]
        st.markdown(f'<div class="note{" fresh" if fresh else ""}"><b>{title}</b>{html.escape(msg["text"])}<br>'
                    f'<a href="{CONTACT_URL}" target="_blank" rel="noopener">לכל הדרכים ליצור קשר עם הפניקס</a></div>',
                    unsafe_allow_html=True)
        return
    if status == "clarify":
        st.markdown(f'<div class="note ask{" fresh" if fresh else ""}"><b>שאלה קטנה לפני שאני עונה</b>{html.escape(msg["text"])}</div>',
                    unsafe_allow_html=True)
        return
    trust = trust_html(msg) if status == "answer" and msg.get("sources") else ""
    st.markdown(f'<div class="answer{" fresh" if fresh else ""}"><div class="answer-body">\n\n{_md(msg["text"])}\n\n</div>{trust}</div>',
                unsafe_allow_html=True)
    if status == "answer" and msg.get("evidence"):
        with st.expander(f"הראו לי איפה זה כתוב ({len(msg['evidence'])})"):
            st.markdown(evidence_html(msg["evidence"]), unsafe_allow_html=True)


def _md_to_html(text):
    """markdown פשוט (מודגש, רשימות, פסקאות) ל-HTML בטוח - לקובץ השיחה."""
    out, items = [], []
    for line in html.escape(text, quote=False).split("\n"):
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line.strip())
        item = re.match(r"^(?:[-•*]|\d+\.)\s+(.*)", line)
        if item:
            items.append(f"<li>{item.group(1)}</li>")
            continue
        if items:
            out.append("<ul>" + "".join(items) + "</ul>")
            items = []
        if line:
            out.append(f"<p>{line}</p>")
    if items:
        out.append("<ul>" + "".join(items) + "</ul>")
    return "".join(out)


def transcript(messages):
    """השיחה כדף מעוצב (HTML) להורדה: נפתח בכל דפדפן, נראה כמו הצ'אט, ואפשר להדפיס או לשמור כ-PDF."""
    when = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%d/%m/%Y %H:%M")
    parts = []
    for m in messages:
        if m["role"] == "user":
            parts.append(f'<div class="q">{html.escape(m["text"])}</div>')
            continue
        body = _md_to_html(m["text"])
        links = "".join(f'<a href="{html.escape(s["url"])}">{html.escape(s["title"])}</a>' for s in m.get("sources") or [])
        quotes = "".join(f'<blockquote>„{html.escape(e["quote"])}”<small>{html.escape(e["title"])}</small></blockquote>'
                         for e in m.get("evidence") or [])
        extra = (f'<div class="src">מקור: {links}</div>' if links else "") + quotes
        parts.append(f'<div class="a"><span class="who">העוזר הדיגיטלי</span>{body}{extra}</div>')
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>שיחה עם העוזר הדיגיטלי של הפניקס</title>
<style>
body {{font-family: Rubik, 'Segoe UI', Arial, sans-serif; background: #F5F6FA; color: #111C3F; margin: 0; padding: 24px;}}
.wrap {{max-width: 760px; margin: 0 auto;}}
header {{background: #fff; border-radius: 14px; padding: 16px 20px; border-bottom: 3px solid #FF4E31;
  box-shadow: 0 2px 15px rgba(0,0,0,.08); margin-bottom: 24px;}}
header b {{font-size: 1.2rem;}} header span {{display: block; color: #6B6E77; font-size: .9rem; margin-top: 2px;}}
.q {{background: #111C3F; color: #fff; padding: 10px 16px; border-radius: 20px 20px 4px 20px; width: fit-content;
  max-width: 85%; margin: 18px 0 8px auto; margin-left: 0;}}
.a {{background: #fff; border-radius: 12px; padding: 14px 18px; box-shadow: 0 2px 15px rgba(0,0,0,.08); line-height: 1.7;}}
.a p {{margin: 0 0 8px;}} .who {{display: block; color: #6B6E77; font-size: .8rem; margin-bottom: 4px;}}
.src {{border-top: 1px solid #EEEFF2; margin-top: 8px; padding-top: 8px; font-size: .9rem; color: #6B6E77;}}
.src a {{color: #111C3F; background: #F2FAFE; border: 1px solid #D6EEF9; border-radius: 20px; padding: 2px 10px;
  margin-inline-start: 6px; text-decoration: none;}}
blockquote {{margin: 8px 0 0; padding: 8px 12px; border-right: 3px solid #FF4E31; background: #FFF8F6; border-radius: 6px;
  font-size: .95rem;}} blockquote small {{display: block; color: #6B6E77; margin-top: 2px;}}
footer {{color: #6B6E77; font-size: .8rem; margin-top: 28px; text-align: center;}}
@media print {{body {{background: #fff;}} .a, header {{box-shadow: none; border: 1px solid #E0DFDF;}}}}
</style></head><body><div class="wrap">
<header><b>שיחה עם העוזר הדיגיטלי של הפניקס</b><span>{when} · התשובות מבוססות על המידע באתר fnx.co.il</span></header>
{"".join(parts)}
<footer>הבוט מסביר מה כתוב באתר ואינו נותן ייעוץ אישי. לבירורים אישיים: שירות הלקוחות של הפניקס.</footer>
</div></body></html>"""


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
                progress.markdown(f'<div class="typing"><span></span><span></span><span></span>{html.escape(value)}</div>',
                                  unsafe_allow_html=True)
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
    show(msg, fresh=True)
    return msg


# ---------- טעינה ----------
try:
    manifest, cache = load_bot()
except IndexNotReady as e:
    st.error(f"הבוט לא מוכן: {e}")
    st.stop()

# ---------- השיחה ----------
TOPICS = [("🏠", "דירה", "ספרו לי על ביטוח דירה"), ("🚗", "רכב", "ספרו לי על ביטוח רכב"),
          ("✈️", "נסיעות לחו\"ל", "ספרו לי על ביטוח נסיעות לחו\"ל"), ("❤️", "בריאות", "ספרו לי על ביטוח בריאות"),
          ("🐾", "חיות מחמד", "ספרו לי על ביטוח לחיות מחמד"), ("💰", "פנסיה וחיסכון", "ספרו לי על פנסיה וחיסכון")]


def greeting():
    """ברכה לפי השעה בישראל - נגיעה קטנה שהופכת את הפתיחה לאישית."""
    try:
        hour = datetime.now(ZoneInfo("Asia/Jerusalem")).hour
    except Exception:
        hour = datetime.now().hour
    return "בוקר טוב" if 5 <= hour < 12 else "צהריים טובים" if hour < 17 else "ערב טוב" if hour < 22 else "שלום"


def ask(q):
    st.session_state.pending = q


def on_feedback(i):
    """👍 / 👎 על תשובה: נרשם (בלי פרטים מזהים) כדי שהמנהל יראה אילו תשובות לא עזרו."""
    value = st.session_state.get(f"fb{i}")
    msgs = st.session_state.messages
    if value is None or i >= len(msgs):
        return
    question = msgs[i - 1]["text"] if i > 0 and msgs[i - 1]["role"] == "user" else ""
    log_feedback(question, msgs[i]["text"], msgs[i].get("status"), value == 1)
    st.toast("תודה! המשוב עוזר לנו להשתפר." if value == 1 else "תודה על המשוב - נבדוק איך לשפר את התשובה.")


st.markdown(f'<div class="topbar"><div class="brand"><div class="dot">💬</div><div><b>העוזר הדיגיטלי של הפניקס</b>'
            f'<span>תשובות מתוך אתר fnx.co.il</span></div></div>'
            f'<a href="{CONTACT_URL}" target="_blank" rel="noopener">דברו עם נציג</a></div>', unsafe_allow_html=True)
if "messages" not in st.session_state:
    st.session_state.messages = []

# תיבת הכתיבה תמיד מוצמדת לתחתית; קוראים אותה כבר כאן כדי לא להציג את מסך הפתיחה מעל שאלה שנשלחה
question = st.chat_input("כתבו שאלה...", max_chars=MAX_CHARS) or st.session_state.pop("pending", None)

if not st.session_state.messages and not question:
    st.markdown(f'<div class="welcome"><h1>{greeting()}, איך אפשר לעזור?</h1>'
                '<p>אפשר לשאול אותי על ביטוח, תביעות, פנסיה וחיסכון. אני עונה לפי המידע שבאתר הפניקס, '
                'ולכל תשובה מצרף קישור לעמוד שממנו היא נלקחה.</p></div>', unsafe_allow_html=True)
    st.markdown('<div class="label">במה מדובר?</div>', unsafe_allow_html=True)
    with st.container(key="topics"):
        cols = st.columns(3)
        for i, (icon, name, q) in enumerate(TOPICS):
            cols[i % 3].button(f"{icon}\n\n{name}", key=f"tp{i}", on_click=ask, args=(q,), use_container_width=True)
    st.markdown('<div class="label">שאלות שלקוחות שואלים</div>', unsafe_allow_html=True)
    with st.container(key="examples", horizontal=True):
        for i, (icon, ex) in enumerate(EXAMPLES):
            st.button(ex, key=f"ex{i}", on_click=ask, args=(ex,))
    crawled = manifest.get("newest_crawl") or ""
    try:
        age = f" (לפני {(date.today() - datetime.fromisoformat(crawled).date()).days} ימים)"
    except ValueError:
        age = ""
    # Streamlit גולל צ'אט תמיד לתחתית; במסך הפתיחה רוצים לראות את הברכה - גוללים פעם אחת למעלה
    components.html("""<script>
      const toTop = () => {
        const box = window.parent.document.querySelector('[data-testid="stAppScrollToBottomContainer"]');
        if (box) box.scrollTop = 0;
      };
      // התוכן ממשיך להיטען (גופנים, כפתורים) ו-Streamlit גולל שוב לתחתית - מחזירים למעלה בשתי השניות הראשונות
      // (עד שהלקוח גולל או מקליד בעצמו)
      let stop = false;
      ["wheel", "touchstart", "keydown"].forEach(e => window.parent.addEventListener(e, () => stop = true, {once: true}));
      const t0 = Date.now();
      const iv = setInterval(() => { if (stop || Date.now() - t0 > 6000) return clearInterval(iv); toTop(); }, 120);
    </script>""", height=0)
    st.markdown(f'<div class="about">🛡️ הבוט מסביר מה כתוב באתר. הוא לא נותן ייעוץ אישי ואין לו גישה לפוליסה שלכם - '
                f'את אלה בודקים בשירות הלקוחות. המידע נאסף מהאתר ב-{html.escape(crawled)}{age}. '
                f'השיחה לא נשמרת אחרי סגירת החלון.</div>', unsafe_allow_html=True)

for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        show(msg)
        if msg["role"] == "assistant" and msg.get("status") in ("answer", "not_found", "clarify"):
            with st.container(key=f"fbrow{i}", horizontal=True):
                st.markdown('<span class="fbq">עזרתי?</span>', unsafe_allow_html=True)
                st.feedback("thumbs", key=f"fb{i}", on_change=on_feedback, args=(i,))

last = st.session_state.messages[-1] if st.session_state.messages else None
if last and last["role"] == "assistant" and not question:
    asked = {m["text"] for m in st.session_state.messages if m["role"] == "user"}
    if last.get("followups"):
        title, chips = "רוצים לדעת עוד?", last["followups"]
    elif last.get("status") != "clarify":  # אחרי "לא מצאתי" / שיחה - לא משאירים את הלקוח בלי כיוון
        title = "אולי תרצו לשאול על:"
        chips = [q for _, _, q in TOPICS if q not in asked][:3]
    else:
        chips = []
    if chips:
        st.markdown(f'<div class="more">{title}</div>', unsafe_allow_html=True)
        with st.container(key="followups", horizontal=True):
            for j, fq in enumerate(chips):
                st.button(fq, key=f"fu{len(st.session_state.messages)}_{j}", on_click=ask, args=(fq,))

if st.session_state.messages and not question:
    with st.container(key="actions", horizontal=True):
        if st.button("↺ שיחה חדשה"):
            for k in [k for k in st.session_state if str(k).startswith("fb")]:
                del st.session_state[k]
            st.session_state.messages = []
            st.rerun()
        st.download_button("⤓ הורדת השיחה", transcript(st.session_state.messages).encode("utf-8"),
                           file_name=f"שיחה-עם-הפניקס-{datetime.now():%Y-%m-%d}.html", mime="text/html")

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

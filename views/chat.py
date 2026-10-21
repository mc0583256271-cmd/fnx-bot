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
from datetime import datetime
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
[data-testid="stToolbar"], [data-testid="stDecoration"], footer, section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] {display: none !important;}
/* כל רוחב המסך: סרגל צד קבוע בימין (300px), והשיחה ממלאת את השאר */
:root {--side: 300px;}
.block-container {padding: 2rem 2.5rem 7rem; padding-right: calc(var(--side) + 2.5rem); max-width: none;}
[data-testid="stBottom"] {width: 100% !important; z-index: 50 !important;}
[data-testid="stBottomBlockContainer"] {padding-right: calc(var(--side) + 2.5rem); padding-left: 2.5rem;
  max-width: none !important; width: 100%;}
[data-testid="stChatInput"] {max-width: none;}
/* מקום שמור מתחת לשיחה: השאלה החדשה עולה לראש המסך מהרגע הראשון, ולא "קופצת" כשהתשובה נגמרת */
.block-container:has(.msg-user) {padding-bottom: calc(100vh - 240px);}

/* בזמן שנכתבת תשובה חדשה Streamlit משאיר את רכיבי המסך הקודם "דהויים" עד שהם מוחלפים - כך נראתה התשובה
   הקודמת מתחת לשאלה החדשה. מסתירים אותם: רואים רק את השאלה החדשה ואת התשובה שנכתבת */
[data-stale="true"] {display: none !important;}

/* סרגל צד - כחול הפניקס, כמו בצ'אטבוטים מקצועיים: מותג, פעולות, נושאים, מידע */
.st-key-side {position: fixed; top: 0; right: 0; bottom: 0; width: var(--side); z-index: 1000;
  background: linear-gradient(180deg, #16234D 0%, var(--blue) 55%, #0C1530 100%); color: #fff;
  box-shadow: -6px 0 28px rgba(17,28,63,.18); padding: 1.4rem 1.1rem 1rem; overflow-y: auto; gap: .6rem;}
.st-key-side, .st-key-side * {direction: rtl; text-align: right;}
.st-key-side::before {content: ""; position: absolute; top: 0; right: 0; left: 0; height: 4px; background: var(--orange);}
.brand {display: flex; align-items: center; gap: .7rem; padding-bottom: 1rem; border-bottom: 1px solid rgba(255,255,255,.12);}
.brand .dot {width: 2.6rem; height: 2.6rem; border-radius: 12px; background: var(--orange); color: #fff;
  display: grid; place-items: center; flex: none; box-shadow: 0 4px 14px rgba(255,78,49,.35);}
.brand b {display: block; font-size: 1.12rem; font-weight: 700; color: #fff;}
.brand span {display: block; color: rgba(255,255,255,.62); font-size: .82rem;}
.st-key-side_actions {gap: .5rem; margin-top: .3rem;}
.st-key-side .stButton button, .st-key-side .stLinkButton a {border-radius: 10px; font-weight: 500; padding: .6rem .9rem;
  min-height: 0; justify-content: center;}
.st-key-side .stButton button[kind="primary"] {background: var(--orange); border-color: var(--orange); color: #fff;
  font-size: 1rem; box-shadow: 0 6px 16px rgba(255,78,49,.3);}
.st-key-side .stButton button[kind="primary"]:hover {background: #FF6448; border-color: #FF6448; color: #fff;}
.st-key-side .stLinkButton a {background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.28); color: #fff;}
.st-key-side .stLinkButton a:hover {background: rgba(255,255,255,.12); border-color: rgba(255,255,255,.5); color: #fff;}
.side-label {color: rgba(255,255,255,.5); font-size: .76rem; font-weight: 600; letter-spacing: .02em;
  margin: 1.1rem .2rem .6rem; line-height: 1.3;}
.st-key-side_more {gap: .1rem;}
.st-key-side_more .stButton button {color: rgba(255,255,255,.9); padding: .5rem .65rem; border-radius: 8px; font-size: .95rem;
  border-color: transparent; background: transparent; box-shadow: none; justify-content: flex-start; gap: .6rem;}
.st-key-side_more .stButton button:hover {background: rgba(255,255,255,.08); color: #fff; border-color: transparent;}
.st-key-side_more .stButton button, .st-key-side_more .stButton button > div {justify-content: flex-start !important;}
.st-key-side_more [data-testid="stElementContainer"], .st-key-side_more .stButton {width: 100% !important;}
.st-key-side_more .stButton button [data-testid="stIconMaterial"] {color: var(--orange);}
.how {list-style: none; padding: 0; margin: 0; font-size: .86rem; color: rgba(255,255,255,.72); line-height: 1.5;}
.how li {display: flex; gap: .55rem; align-items: flex-start; margin: 0 0 .6rem;}
.how li span:last-child {flex: 1 1 auto; text-align: right;}
.how .material {font-size: 1.1rem; flex: none; color: var(--orange);}
.side-foot {margin-top: .8rem; padding-top: .8rem; border-top: 1px solid rgba(255,255,255,.12);
  color: rgba(255,255,255,.45); font-size: .76rem; line-height: 1.6;}
.st-key-end_actions {margin-top: .8rem;}
.st-key-end_actions .stDownloadButton button {border-radius: 22px; border: 1px solid var(--line); background: var(--paper);
  color: var(--blue); font-weight: 500; font-size: .9rem; padding: .35rem 1rem;}
.st-key-end_actions .stDownloadButton button:hover {border-color: var(--blue);}
[data-testid="stIconMaterial"] {color: inherit;}

/* טלפון וטאבלט: הסרגל הופך לפס עליון קומפקטי */
@media (max-width: 900px) {
  :root {--side: 0px;}
  .block-container {padding: 0 1rem 7rem;}
  .block-container:has(.msg-user) {padding-bottom: calc(100vh - 220px);}
  [data-testid="stBottomBlockContainer"] {padding: 0 1rem 1rem;}
  [data-testid="stLayoutWrapper"]:has(> .st-key-side) {position: sticky; top: .4rem; z-index: 80;}
  .st-key-side {position: relative; top: 0; bottom: auto; width: auto; flex-direction: row; align-items: center;
    flex-wrap: nowrap; padding: .55rem .7rem; margin: .4rem 0 .8rem; border-radius: 14px;
    box-shadow: 0 2px 12px rgba(17,28,63,.1); border-left: none; overflow: hidden;}
  .st-key-side::before {top: auto; bottom: 0;}
  .st-key-side {background: var(--blue);}
  .st-key-side_more, [data-testid="stLayoutWrapper"]:has(> .st-key-side_more) {display: none !important;}
  [data-testid="stLayoutWrapper"]:has(> .st-key-side_actions) {flex: none; width: auto !important;}
  .brand {border: none; padding: 0; flex: 1 1 auto; min-width: 0;}
  .st-key-side > [data-testid="stElementContainer"]:first-child {flex: 1 1 auto; min-width: 0; width: auto !important;}
  .brand b {overflow: hidden; text-overflow: ellipsis;}
  .brand .dot {width: 2.1rem; height: 2.1rem;}
  .brand b {font-size: .95rem; white-space: nowrap;} .brand span {display: none;}
  .st-key-side_actions {flex-direction: row; margin: 0; width: auto !important; flex: none;}
  .st-key-side_actions [data-testid="stElementContainer"] {width: auto !important;}
  .st-key-side .stButton button p, .st-key-side .stLinkButton a p {display: none;}
  .st-key-side .stButton button, .st-key-side .stLinkButton a {padding: .45rem .6rem;}
}

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
.st-key-topics .stButton button {flex-direction: column; gap: .35rem;}
.st-key-topics .stButton button [data-testid="stIconMaterial"] {color: var(--orange); font-size: 2rem; margin: 0;}
.st-key-examples .stButton button [data-testid="stIconMaterial"], .st-key-followups .stButton button [data-testid="stIconMaterial"]
  {color: var(--orange); font-size: 1.05rem;}
.material {font-family: 'Material Symbols Rounded'; font-size: 1.05rem; vertical-align: -3px; color: var(--orange);}
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
.about {margin-top: 1.1rem; color: var(--gray); font-size: .84rem; line-height: 1.55;}

/* תיבת הכתיבה */
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {background: var(--surface);}
[data-testid="stChatInput"] {background: var(--paper); border: 1px solid var(--line); border-radius: 26px; box-shadow: var(--shadow);}
[data-testid="stChatInput"]:focus-within {border-color: var(--blue);}
[data-testid="stChatInputSubmitButton"] {background: var(--orange) !important; color: #fff !important; border-radius: 50% !important;}
@media (max-width: 640px) {.welcome h1 {font-size: 1.8rem;}
}
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


WHO = '<div class="who"><i></i>העוזר הדיגיטלי</div>'


def show_body(msg):
    """גוף ההודעה של הבוט (בלי התווית) - משמש גם לתשובה החדשה, שמוצגת באותו מקום שבו נכתבה."""
    status = msg.get("status")
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


def show(msg):
    if msg["role"] == "user":
        st.markdown(f'<div class="msg-user">{html.escape(msg["text"])}</div>', unsafe_allow_html=True)
        return
    st.markdown(WHO, unsafe_allow_html=True)
    show_body(msg)


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
        if m.get("status") in ("not_found", "personal", "unavailable"):
            body += f'<div class="src"><a href="{CONTACT_URL}">לכל הדרכים ליצור קשר עם הפניקס</a></div>'
        sources = m.get("sources") or [] if m.get("status") == "answer" else []
        links = "".join(f'<a href="{html.escape(s["url"])}">{html.escape(s["title"])}</a>' for s in sources)
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
    """כותב את התשובה תוך כדי הזרמה, ובסוף מציג את הגרסה הסופית באותו מקום בדיוק (box).
    לא מוחקים ולא מציירים מחדש את הדף - זה מה שגרם ל"קפיצה" בסוף כל תשובה."""
    key = (manifest["built_at"], normalize(question))
    st.markdown(WHO, unsafe_allow_html=True)
    box = st.empty()
    if not history and key in cache:  # שאלה ראשונה שכבר נשאלה - מיד, בלי לפנות למודל
        result = cache[key]
    else:
        result = None
        for kind, value in answer_stream(question, history=history):
            if kind == "status":
                box.markdown(f'<div class="typing"><span></span><span></span><span></span>{html.escape(value)}</div>',
                             unsafe_allow_html=True)
            elif kind == "text":
                box.markdown(f'<div class="answer"><div class="answer-body">\n\n{_md(value)} '
                             f'<span class="cursor">▌</span>\n\n</div></div>', unsafe_allow_html=True)
            else:
                result = value
        if not history and result["status"] in ("answer", "not_found"):
            cache[key] = result
        if result["status"] == "not_found":
            log_gap(question, result.get("search_query"), result.get("reason"))
    msg = {"role": "assistant", "text": result["answer"], "status": result["status"],
           "sources": result.get("sources", []), "evidence": result.get("evidence", []),
           "trust": result.get("trust"), "followups": result.get("followups", [])}
    with box.container():  # הגרסה הסופית (עם מקורות וציטוטים) מחליפה את הטקסט שנכתב - באותו מקום
        show_body(msg)
    return msg


# ---------- טעינה ----------
try:
    manifest, cache = load_bot()
except IndexNotReady as e:
    st.error(f"הבוט לא מוכן: {e}")
    st.stop()

# ---------- השיחה ----------
# אייקונים קוויים (Material Symbols) בכתום - כמו אייקוני המוצרים באתר הפניקס
TOPICS = [(":material/home:", "דירה", "ספרו לי על ביטוח דירה"),
          (":material/directions_car:", "רכב", "ספרו לי על ביטוח רכב"),
          (":material/flight:", "נסיעות לחו\"ל", "ספרו לי על ביטוח נסיעות לחו\"ל"),
          (":material/health_and_safety:", "בריאות", "ספרו לי על ביטוח בריאות"),
          (":material/pets:", "חיות מחמד", "ספרו לי על ביטוח לחיות מחמד"),
          (":material/savings:", "פנסיה וחיסכון", "ספרו לי על פנסיה וחיסכון")]
CHAT_ICON = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 '
             '20.5l1.4-4.9A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/></svg>')


def greeting():
    """ברכה לפי השעה בישראל - נגיעה קטנה שהופכת את הפתיחה לאישית."""
    try:
        hour = datetime.now(ZoneInfo("Asia/Jerusalem")).hour
    except Exception:
        hour = datetime.now().hour
    return "בוקר טוב" if 5 <= hour < 12 else "צהריים טובים" if hour < 17 else "ערב טוב" if hour < 22 else "שלום"


def ask(q):
    st.session_state.pending = q


def new_chat():
    for k in [k for k in st.session_state if str(k).startswith("fb")]:
        del st.session_state[k]
    st.session_state.messages = []
    st.session_state.pop("pending", None)


def on_feedback(i):
    """👍 / 👎 על תשובה: נרשם (בלי פרטים מזהים) כדי שהמנהל יראה אילו תשובות לא עזרו."""
    value = st.session_state.get(f"fb{i}")
    msgs = st.session_state.messages
    if value is None or i >= len(msgs):
        return
    question = msgs[i - 1]["text"] if i > 0 and msgs[i - 1]["role"] == "user" else ""
    log_feedback(question, msgs[i]["text"], msgs[i].get("status"), value == 1)
    st.toast("תודה! המשוב עוזר לנו להשתפר." if value == 1 else "תודה על המשוב - נבדוק איך לשפר את התשובה.")


def scroll_to_question(n, seconds):
    """גולל כך שהשאלה האחרונה תהיה בראש המסך (מתחת לפס העליון), והתשובה נכתבת מתחתיה.
    Streamlit גולל צ'אט לתחתית בכל פעם שהתוכן גדל - לכן מחזירים את המיקום כמה שניות, עד שהלקוח גולל בעצמו.
    n משנה את התוכן כך שהסקריפט ירוץ מחדש לכל שאלה."""
    components.html(f"""<script>/* q{n} */
      const doc = window.parent.document;
      const go = () => {{
        const box = doc.querySelector('[data-testid="stAppScrollToBottomContainer"]');
        const qs = doc.querySelectorAll('.msg-user');
        const q = qs[qs.length - 1];
        if (!box || !q) return;
        const bar = window.parent.innerWidth <= 900 ? doc.querySelector('.st-key-side') : null;
        const offset = (bar ? bar.getBoundingClientRect().height : 0) + 24;
        const delta = q.getBoundingClientRect().top - box.getBoundingClientRect().top - offset;
        if (Math.abs(delta) < 2) return;
        // התנועה הראשונה חלקה (גלישה), התיקונים אחריה מיידיים וקטנים - בלי קפיצות
        if (!window.__glided) {{ window.__glided = true; box.scrollBy({{top: delta, behavior: "smooth"}}); }}
        else if (!window.__gliding) box.scrollTop += delta;
      }};
      window.__glided = false; window.__gliding = true; setTimeout(() => window.__gliding = false, 450);
      let stop = false;
      ["wheel", "touchmove", "keydown"].forEach(e => doc.addEventListener(e, () => stop = true, {{once: true}}));
      const t0 = Date.now();
      const iv = setInterval(() => {{ if (stop || Date.now() - t0 > {seconds * 1000}) return clearInterval(iv); go(); }}, 150);
    </script>""", height=0)


if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------- סרגל צד (בימין): מותג, שיחה חדשה, נציג, נושאים, איך זה עובד ----------
crawled = manifest.get("newest_crawl") or ""
try:
    crawled_nice = datetime.fromisoformat(crawled).strftime("%d/%m/%Y")
except ValueError:
    crawled_nice = crawled
with st.container(key="side"):
    st.markdown(f'<div class="brand"><div class="dot">{CHAT_ICON}</div><div><b>העוזר הדיגיטלי</b>'
                f'<span>הפניקס · תשובות מתוך האתר</span></div></div>', unsafe_allow_html=True)
    with st.container(key="side_actions"):
        st.button("שיחה חדשה", icon=":material/add_comment:", key="new_chat", on_click=new_chat, type="primary",
                  use_container_width=True)
        st.link_button("דברו עם נציג", CONTACT_URL, icon=":material/support_agent:", use_container_width=True)
    with st.container(key="side_more"):
        st.markdown('<div class="side-label">נושאים</div>', unsafe_allow_html=True)
        for i, (icon, name, q) in enumerate(TOPICS):
            st.button(name, icon=icon, key=f"side{i}", on_click=ask, args=(q,), type="tertiary", use_container_width=True)
        st.markdown(f"""<div class="side-label">איך זה עובד</div>
<ul class="how">
<li><span class="material">language</span><span>עונה רק לפי המידע באתר הפניקס</span></li>
<li><span class="material">link</span><span>לכל תשובה מצורף העמוד שממנו היא נלקחה</span></li>
<li><span class="material">fact_check</span><span>המשפטים מהאתר נבדקים לפני שהתשובה מוצגת</span></li>
<li><span class="material">lock</span><span>אין גישה לפרטים אישיים - אותם בודקים בשירות הלקוחות</span></li>
</ul>
<div class="side-foot">המידע נאסף מהאתר ב-{html.escape(crawled_nice)} · {manifest.get("pages", "")} עמודים<br>
השיחה לא נשמרת אחרי סגירת החלון</div>""", unsafe_allow_html=True)

# תיבת הכתיבה תמיד מוצמדת לתחתית; קוראים אותה כבר כאן כדי לא להציג את מסך הפתיחה מעל שאלה שנשלחה
question = st.chat_input("כתבו שאלה...", max_chars=MAX_CHARS) or st.session_state.pop("pending", None)

# אם הלקוח לחץ על כפתור בזמן שהתשובה נכתבה, Streamlit עוצר את הכתיבה והשאלה נשארת בלי תשובה.
# במקרה כזה עונים עליה עכשיו (לפני שאלה חדשה, אם נשלחה) - אף שאלה לא נשארת תלויה באוויר.
msgs = st.session_state.messages
if msgs and msgs[-1]["role"] == "user":
    if question:
        st.session_state.pending = question  # השאלה החדשה תיענה מיד אחרי
    question = msgs.pop()["text"]
if question:
    question = question.strip()[:MAX_CHARS]
    if question and rate_limited():
        st.toast("נשאלו הרבה שאלות בזמן קצר. אפשר לנסות שוב בעוד דקה.")
        question = None

if not st.session_state.messages and not question:
    st.markdown(f'<div class="welcome"><h1>{greeting()}, איך אפשר לעזור?</h1>'
                '<p>אפשר לשאול אותי על ביטוח, תביעות, פנסיה וחיסכון. אני עונה לפי המידע שבאתר הפניקס, '
                'ולכל תשובה מצרף קישור לעמוד שממנו היא נלקחה.</p></div>', unsafe_allow_html=True)
    st.markdown('<div class="label">במה מדובר?</div>', unsafe_allow_html=True)
    with st.container(key="topics"):
        cols = st.columns(3)
        for i, (icon, name, q) in enumerate(TOPICS):
            cols[i % 3].button(name, icon=icon, key=f"tp{i}", on_click=ask, args=(q,), use_container_width=True)
    st.markdown('<div class="label">שאלות שלקוחות שואלים</div>', unsafe_allow_html=True)
    with st.container(key="examples", horizontal=True):
        for i, (icon, ex) in enumerate(EXAMPLES):
            st.button(ex, key=f"ex{i}", on_click=ask, args=(ex,), icon=":material/chat_bubble:")
    # Streamlit גולל צ'אט תמיד לתחתית; במסך הפתיחה רוצים לראות את הברכה - גוללים למעלה
    components.html("""<script>
      const toTop = () => {
        const box = window.parent.document.querySelector('[data-testid="stAppScrollToBottomContainer"]');
        if (box) box.scrollTop = 0;
      };
      let stop = false;
      ["wheel", "touchstart", "keydown"].forEach(e => window.parent.addEventListener(e, () => stop = true, {once: true}));
      const t0 = Date.now();
      const iv = setInterval(() => {
        // נעצר מיד כשנשלחת שאלה (אחרת הוא "מושך" את המסך למעלה בזמן שהתשובה נכתבת)
        if (stop || Date.now() - t0 > 6000 || window.parent.document.querySelector('.msg-user')) return clearInterval(iv);
        toTop();
      }, 120);
    </script>""", height=0)


def feedback_row(i):
    with st.container(key=f"fbrow{i}", horizontal=True):
        st.markdown('<span class="fbq">עזרתי?</span>', unsafe_allow_html=True)
        st.feedback("thumbs", key=f"fb{i}", on_change=on_feedback, args=(i,))


# כל הודעה מצוירת תמיד באותו מקום בדף (Streamlit מזהה רכיבים לפי מיקום): השאלה החדשה נכנסת לסוף הרשימה ונענית
# באותה לולאה - כך היא לא "יורשת" מקום שהיה שייך לתשובה קודמת (שאריות של התשובה הקודמת נראו מתחת לשאלה).
if question:
    history = [{"role": m["role"], "text": m["text"]} for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "text": question})

for i, msg in enumerate(list(st.session_state.messages)):
    is_new = bool(question) and i == len(st.session_state.messages) - 1 and msg["role"] == "user"
    with st.chat_message(msg["role"]):
        show(msg)
        if is_new:
            scroll_to_question(i, seconds=45)  # השאלה בראש המסך, התשובה נכתבת מתחתיה
        if msg["role"] == "assistant" and msg.get("status") in ("answer", "not_found", "clarify"):
            feedback_row(i)
    if is_new:  # התשובה לשאלה החדשה - נכתבת ונשמרת באותה ריצה, בלי לצייר את הדף מחדש
        with st.chat_message("assistant"):
            reply = respond(question, history, manifest, cache)
            st.session_state.messages.append(reply)
            if reply.get("status") in ("answer", "not_found", "clarify"):
                feedback_row(len(st.session_state.messages) - 1)
        if st.session_state.get("pending"):  # נשלחה עוד שאלה בזמן הכתיבה - עונים עליה עכשיו
            st.rerun()

last = st.session_state.messages[-1] if st.session_state.messages else None
if last and last["role"] == "assistant":
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
        with st.container(key=f"followups{len(st.session_state.messages)}", horizontal=True):
            for j, fq in enumerate(chips):
                st.button(fq, key=f"fu{len(st.session_state.messages)}_{j}", on_click=ask, args=(fq,),
                          icon=":material/subdirectory_arrow_left:")
    with st.container(key="end_actions", horizontal=True):
        st.download_button("הורדת השיחה", transcript(st.session_state.messages).encode("utf-8"),
                           icon=":material/download:", key=f"dl{len(st.session_state.messages)}",
                           file_name=f"שיחה-עם-הפניקס-{datetime.now():%Y-%m-%d}.html", mime="text/html",
                           help="דף מעוצב שנפתח בדפדפן - אפשר להדפיס או לשמור כ-PDF")

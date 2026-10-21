"""
עמוד המנהל (כתובת: /admin). לא מקושר מהצ'אט, ונכנסים אליו עם סיסמה.

- מצב המידע: מתי נאסף, כמה עמודים ופסקאות.
- רענון המידע מהאתר ברקע (core/refresh.py), ודוח "מה השתנה באתר" אחרי הסריקה.
- מכ"ם פערים: שאלות שהבוט לא מצא להן תשובה (core/gaps.py) - מה לקוחות מחפשים ולא מוצאים באתר.

הסיסמה: ADMIN_PASSWORD ב-.env או ב-Secrets של Streamlit Cloud. בלעדיה העמוד סגור.
"""
import hmac
import html
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.embeddings import Stop, load_key  # noqa: E402
from core.gaps import load_gaps  # noqa: E402
from core.refresh import RefreshJob  # noqa: E402

MAX_FAILS = 5            # ניסיונות שגויים בחלון אחד לפני נעילה
LOCK_SECONDS = 300
GLOBAL_MAX_FAILS = 30    # ניסיונות שגויים בכל השרת ב-10 דקות (מפני ניחוש מחלונות רבים)

st.set_page_config(page_title="ניהול הבוט", page_icon="🔒", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700;800&display=swap');
html, body, .stApp, .stMarkdown, .stButton button, input {font-family: 'Assistant', 'Segoe UI', Arial, sans-serif;}
.stApp {background: #F3F6F7; color: #12304A;}
.block-container {direction: rtl; text-align: right; max-width: 860px; padding-top: 2rem;}
[data-testid="stToolbar"], [data-testid="stDecoration"], footer, section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] {display: none !important;}
h1 {font-weight: 800; letter-spacing: -.02em;}
.card {background: #fff; border: 1px solid #DCE3E8; border-radius: 14px; padding: 1rem 1.2rem; margin-bottom: 1rem;}
.big {font-size: 1.9rem; font-weight: 800; line-height: 1.1;}
.muted {color: #5C6B78; font-size: .92rem;}
.gap {display: flex; justify-content: space-between; gap: 1rem; padding: .45rem 0; border-bottom: 1px solid #EEF2F4;}
.gap b {color: #0E7C7B; white-space: nowrap;}
.stButton button {border-radius: 999px; font-weight: 700;}
pre {direction: rtl; text-align: right;}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def shared():
    """משותף לכל השרת: משימת הרענון (אחת בכל רגע) ומונה ניסיונות כניסה שגויים."""
    return {"job": RefreshJob(), "fails": []}


def admin_password():
    try:
        return load_key("ADMIN_PASSWORD")
    except Stop:
        return None


def login():
    s, now = shared(), time.time()
    s["fails"] = [t for t in s["fails"] if now - t < 600]
    locked_until = st.session_state.get("locked_until", 0)
    if now < locked_until or len(s["fails"]) >= GLOBAL_MAX_FAILS:
        st.error("יותר מדי ניסיונות שגויים. אפשר לנסות שוב בעוד כמה דקות.")
        st.stop()
    with st.form("login"):
        pw = st.text_input("סיסמת מנהל", type="password")
        ok = st.form_submit_button("כניסה")
    if ok:
        real = admin_password()
        if real and hmac.compare_digest(pw.encode(), real.encode()):  # השוואה בזמן קבוע
            st.session_state.admin = True
            st.session_state.fails = 0
            st.rerun()
        s["fails"].append(now)
        st.session_state.fails = st.session_state.get("fails", 0) + 1
        if st.session_state.fails >= MAX_FAILS:
            st.session_state.locked_until = now + LOCK_SECONDS
        st.error("סיסמה שגויה.")
    st.stop()


def manifest():
    try:
        return json.loads((ROOT / "data" / "index" / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def titles_by_url():
    out = {}
    try:
        for line in (ROOT / "data" / "pages.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            out[r["url"]] = r.get("title") or r["url"]
    except Exception:
        pass
    return out


def _csv_safe(text):
    """בלי מרכאות כפולות, ובלי תו פתיחה שאקסל מפרש כנוסחה (=, +, -, @)."""
    text = text.replace('"', "'")
    return "'" + text if text[:1] in "=+-@" else text


STOP = set("של על את עם מה איך כמה אם יש לי זה זו אני אפשר האם או גם כל לא כן מי למה מתי איפה בין אצלכם שלי "
           "ביטוח הפניקס".split())

# ---------------------------------------------------------------- עמוד
st.title("ניהול הבוט")
if admin_password() is None:
    st.warning("עמוד הניהול סגור: לא הוגדרה סיסמת מנהל (ADMIN_PASSWORD ב-.env או ב-Secrets).")
    st.stop()
if not st.session_state.get("admin"):
    login()

if st.button("יציאה", key="logout"):
    st.session_state.admin = False
    st.rerun()

# ---------- מצב המידע ----------
m = manifest()
st.subheader("המידע שהבוט עונה ממנו")
c1, c2, c3 = st.columns(3)
c1.markdown(f'<div class="card"><div class="big">{m.get("pages", "-")}</div><div class="muted">עמודים מהאתר</div></div>',
            unsafe_allow_html=True)
c2.markdown(f'<div class="card"><div class="big">{m.get("chunks", "-")}</div><div class="muted">פסקאות באינדקס</div></div>',
            unsafe_allow_html=True)
c3.markdown(f'<div class="card"><div class="big">{html.escape(str(m.get("newest_crawl", "-")))}</div>'
            f'<div class="muted">נאסף לאחרונה</div></div>', unsafe_allow_html=True)
st.caption(f"האינדקס נבנה ב-{m.get('built_at', '-')} · מודל ההטמעה {m.get('model', '-')}")

# ---------- רענון ----------
st.subheader("רענון המידע מהאתר")
st.write("סורק את אתר הפניקס, מוריד רק עמודים שהשתנו, ובונה את האינדקס מחדש. פסקאות שלא השתנו לא נשלחות שוב "
         "להטמעה. אם הסריקה נכשלת או שיוצא הרבה פחות מידע מקודם - המידע הקודם נשאר והבוט ממשיך לעבוד כרגיל.")
job = shared()["job"]
if job.running():
    st.info(f"רענון רץ עכשיו (התחיל לפני {int(time.time() - job.started)} שניות). אפשר להמשיך לעבוד, הצ'אט לא מושפע.")
    st.code(job.log_tail() or "מתחיל...", language=None)
    if st.button("עדכון מצב"):
        st.rerun()
else:
    if job.finished:
        when = datetime.fromtimestamp(job.finished).strftime("%H:%M")
        if job.returncode == 0:
            st.success(f"הרענון הסתיים בהצלחה ב-{when}. הצ'אט כבר עונה מהמידע החדש.")
        else:
            st.error(f"הרענון נכשל ב-{when} - המידע הקודם נשאר. פרטים:")
        st.code(job.log_tail(), language=None)
    if st.button("רענון המידע מהאתר", type="primary"):
        if job.start():
            st.rerun()
        st.warning("כבר רץ רענון.")

changes_file = ROOT / "data" / "changes.json"
if changes_file.exists():
    try:
        ch = json.loads(changes_file.read_text(encoding="utf-8"))
        names = titles_by_url()
        st.markdown(f"**מה השתנה באתר בסריקה האחרונה** "
                    f"({datetime.fromtimestamp(changes_file.stat().st_mtime):%d/%m/%Y %H:%M})")
        for key, label in [("new", "עמודים חדשים"), ("updated", "עמודים שהתוכן שלהם השתנה"), ("removed", "עמודים שהוסרו")]:
            urls = ch.get(key, [])
            with st.expander(f"{label}: {len(urls)}"):
                for u in urls[:100]:
                    st.markdown(f"- [{names.get(u, u)}]({u})")
    except Exception:
        pass

# ---------- מכ"ם פערים ----------
st.subheader('מכ"ם פערים: מה לקוחות שואלים ולא מוצאים באתר')
gaps = load_gaps()
if not gaps:
    st.write("עדיין אין שאלות שלא נענו. כל שאלה שהבוט עונה עליה \"לא מצאתי\" תופיע כאן - בלי פרטים מזהים.")
else:
    st.write(f"{len(gaps)} שאלות לא נענו. הנושאים שחוזרים הכי הרבה הם רמז למידע שכדאי להוסיף לאתר "
             "(או לשאלות שהבוט מפספס).")
    words = Counter(w for g in gaps for w in set(re.findall(r"[א-ת]{3,}", g["search_query"])) if w not in STOP)
    st.markdown("**מילים שחוזרות:** " + " · ".join(f"{html.escape(w)} ({n})" for w, n in words.most_common(12)),
                unsafe_allow_html=True)
    same = Counter(re.sub(r"[?!.,\s]+", " ", g["question"]).strip() for g in gaps)
    rows = "".join(f'<div class="gap"><span>{html.escape(q)}</span><b>{n}×</b></div>' for q, n in same.most_common(15))
    st.markdown(f'<div class="card">{rows}</div>', unsafe_allow_html=True)
    st.download_button("הורדת כל השאלות שלא נענו (CSV)",
                       "at,question\n" + "\n".join(f'{g["at"]},"{_csv_safe(g["question"])}"' for g in gaps),
                       file_name="unanswered.csv", mime="text/csv")

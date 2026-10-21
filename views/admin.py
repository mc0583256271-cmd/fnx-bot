"""
עמוד המנהל (כתובת: /admin, הניתוב ב-app.py). לא מקושר מהצ'אט, ונכנסים אליו עם סיסמה.

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
from core.gaps import clear_feedback, clear_gaps, load_feedback, load_gaps, remove_question  # noqa: E402
from core.refresh import RefreshJob  # noqa: E402

MAX_FAILS = 5            # ניסיונות שגויים בחלון אחד לפני נעילה
LOCK_SECONDS = 300
GLOBAL_MAX_FAILS = 30    # ניסיונות שגויים בכל השרת ב-10 דקות (מפני ניחוש מחלונות רבים)

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700&display=swap');
html, body, .stApp, .stMarkdown, .stButton button, input {font-family: 'Rubik', 'Segoe UI', Arial, sans-serif;}
.stApp {background: #F5F6FA; color: #111C3F;}
.block-container {direction: rtl; text-align: right; max-width: 880px; padding-top: 2rem;}
[data-testid="stToolbar"], [data-testid="stDecoration"], footer, section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"], header[data-testid="stHeader"] {display: none !important;}
h1 {font-weight: 700; border-bottom: 3px solid #FF4E31; display: inline-block; padding-bottom: .2rem;}
.card {background: #fff; border-radius: 12px; box-shadow: 0 2px 15px rgba(0,0,0,.08); padding: 1rem 1.2rem; margin-bottom: 1rem;}
.big {font-size: 1.9rem; font-weight: 700; line-height: 1.1;}
.muted {color: #6B6E77; font-size: .92rem;}
.gap {display: flex; justify-content: space-between; gap: 1rem; padding: .45rem 0; border-bottom: 1px solid #EEEFF2;}
.gap b {color: #FF4E31; white-space: nowrap;}
.stButton button {border-radius: 22px; font-weight: 500;}
.stButton button[kind="primary"] {background: #FF4E31; border-color: #FF4E31;}
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

# ---------- בדיקת תקינות ----------
st.subheader("בדיקת תקינות")
st.write("בודק שהחיפוש ומודלי השפה עונים, וכמה זמן זה לוקח. מתאים כשהבוט נראה איטי או לא עונה.")
if st.button("הרצת בדיקה"):
    from core.providers import DEFAULT_CHAIN, ClaudeProvider, GeminiProvider, Unavailable
    from core.retriever import Retriever
    checks = []
    t0 = time.time()
    try:
        Retriever().search("איך מגישים תביעה על נזילה?", k=8)
        checks.append(("חיפוש באינדקס", True, f"{time.time() - t0:.1f} שניות"))
    except Exception:  # noqa: BLE001 - למנהל מספיק לדעת שזה לא עובד
        checks.append(("חיפוש באינדקס", False, "לא עובד - כל השאלות יקבלו \"השירות לא זמין\""))
    for label, prov in [("מודל השפה הראשי", ClaudeProvider()),
                        ("מודל הגיבוי", GeminiProvider(DEFAULT_CHAIN[0][0], timeout=20))]:
        t0, first = time.time(), None
        try:
            for _ in prov.stream("ענה במשפט אחד.", "מה זה ביטוח דירה?"):
                first = first or time.time() - t0
            checks.append((label, True, f"מתחיל לענות אחרי {first:.1f} שניות"))
        except Unavailable:
            checks.append((label, False, "לא זמין כרגע"))
    rows = "".join(f'<div class="gap"><span>{"✅" if ok else "⚠️"} {name}</span><b>{html.escape(note)}</b></div>'
                   for name, ok, note in checks)
    st.markdown(f'<div class="card">{rows}</div>', unsafe_allow_html=True)

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
    st.write("אין כרגע שאלות פתוחות. כל שאלה שהבוט עונה עליה \"לא מצאתי\" תופיע כאן - בלי פרטים מזהים.")
else:
    st.write(f"{len(gaps)} שאלות לא נענו. נושאים שחוזרים הם רמז למידע שכדאי להוסיף לאתר. "
             "אחרי שמטפלים בשאלה (למשל מוסיפים מידע לאתר ומרעננים) - מסמנים אותה כ\"טופלה\".")
    words = Counter(w for g in gaps for w in set(re.findall(r"[א-ת]{3,}", g["search_query"])) if w not in STOP)
    st.markdown("**מילים שחוזרות:** " + " · ".join(f"{html.escape(w)} ({n})" for w, n in words.most_common(12)),
                unsafe_allow_html=True)
    same = Counter(re.sub(r"[?!.,\s]+", " ", g["question"]).strip() for g in gaps)
    for i, (q, n) in enumerate(same.most_common(20)):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f'<div class="gap"><span>{html.escape(q)}</span><b>{n}×</b></div>', unsafe_allow_html=True)
        if c2.button("✓ טופלה", key=f"gap{i}"):
            remove_question(q)
            st.rerun()
    st.download_button("הורדת כל השאלות (CSV)",
                       "at,question\n" + "\n".join(f'{g["at"]},"{_csv_safe(g["question"])}"' for g in gaps),
                       file_name="unanswered.csv", mime="text/csv")
    with st.expander("ניקוי כל הרשימה"):
        sure = st.checkbox("כן, למחוק את כל השאלות שלא נענו (אי אפשר לשחזר)", key="sure_gaps")
        if st.button("מחיקת הרשימה", disabled=not sure):
            clear_gaps()
            st.rerun()

# ---------- משוב לקוחות ----------
st.subheader("משוב לקוחות: עזרתי?")
fb = load_feedback()
if not fb:
    st.write("עדיין אין משוב. אחרי כל תשובה לקוחות יכולים ללחוץ 👍 או 👎.")
else:
    good = sum(r["helpful"] for r in fb)
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="card"><div class="big">{round(100 * good / len(fb))}%</div>'
                f'<div class="muted">מהתשובות עזרו</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="card"><div class="big">{good}</div><div class="muted">👍</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="card"><div class="big">{len(fb) - good}</div><div class="muted">👎</div></div>',
                unsafe_allow_html=True)
    bad = [r for r in fb if not r["helpful"]][-10:]
    if bad:
        st.markdown("**תשובות אחרונות שלא עזרו** - כדאי לבדוק אם חסר מידע באתר או שהבוט פספס:")
        rows = "".join(f'<div class="gap"><span><b style="color:#111C3F">{html.escape(r["question"])}</b><br>'
                       f'<span class="muted">{html.escape(r["answer"][:160])}</span></span></div>' for r in reversed(bad))
        st.markdown(f'<div class="card">{rows}</div>', unsafe_allow_html=True)
    with st.expander("ניקוי המשוב"):
        sure = st.checkbox("כן, למחוק את כל המשוב (אי אפשר לשחזר)", key="sure_fb")
        if st.button("מחיקת המשוב", disabled=not sure):
            clear_feedback()
            st.rerun()

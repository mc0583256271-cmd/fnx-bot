"""
עמוד המנהל (כתובת: /admin, הניתוב ב-app.py). לא מקושר מהצ'אט, ונכנסים אליו עם סיסמה.

- מצב המידע: מתי נאסף, כמה עמודים ופסקאות.
- רענון המידע מהאתר ברקע (core/refresh.py), ודוח "מה השתנה באתר" אחרי הסריקה.
- מכ"ם פערים: שאלות שהבוט לא מצא להן תשובה (core/gaps.py) - מה לקוחות מחפשים ולא מוצאים באתר.

הסיסמה: ADMIN_PASSWORD ב-.env או ב-Secrets של Streamlit Cloud. בלעדיה העמוד סגור.
"""
import csv
import hmac
import io
import html
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.embeddings import Stop, load_key  # noqa: E402
from core.gaps import clear_feedback, clear_gaps, load_feedback, load_gaps, remove_question  # noqa: E402
from core.refresh import RefreshJob  # noqa: E402
from core.theme import apply_theme, brand  # noqa: E402

MAX_FAILS = 5            # ניסיונות שגויים בחלון אחד לפני נעילה
LOCK_SECONDS = 300
GLOBAL_MAX_FAILS = 30    # ניסיונות שגויים בכל השרת ב-10 דקות (מפני ניחוש מחלונות רבים)

apply_theme("""
/* עמוד המנהל: אותו סרגל צד כחול, והתוכן בכרטיסים לבנים לפי נושא */
.block-container {padding-bottom: 3rem;}
.page-h {margin: .2rem 0 1.4rem;}
.page-h h1 {font-size: 1.9rem; font-weight: 700; color: var(--blue); margin: 0; padding: 0;}
.page-h span {color: var(--gray);}
[class*="st-key-sec_"] {background: var(--paper); border-radius: 16px; box-shadow: var(--shadow);
  padding: 1.3rem 1.5rem 1.4rem; margin-bottom: 1.2rem; border-top: 3px solid transparent;}
[class*="st-key-sec_"]:hover {border-top-color: var(--orange);}
.anchor {position: relative; top: -1.5rem;}
.sec-h {display: flex; align-items: center; gap: .7rem; margin-bottom: .2rem;}
.sec-h .material {width: 2.3rem; height: 2.3rem; border-radius: 10px; background: var(--orange-soft); color: var(--orange);
  display: grid; place-items: center; font-size: 1.3rem; vertical-align: 0; flex: none;}
.sec-h h3 {font-size: 1.2rem; font-weight: 700; color: var(--blue); margin: 0; padding: 0;}
.card {background: var(--surface); border-radius: 12px; padding: 1rem 1.2rem; margin-bottom: .6rem;}
.big {font-size: 1.9rem; font-weight: 700; line-height: 1.1; color: var(--blue);}
.muted {color: var(--gray); font-size: .92rem;}
.gap {display: flex; justify-content: space-between; gap: 1rem; padding: .5rem 0; border-bottom: 1px solid #EEEFF2;}
.gap b {color: var(--orange); white-space: nowrap;}
.main-area .stButton button, [class*="st-key-sec_"] .stButton button, [class*="st-key-sec_"] .stDownloadButton button,
.stFormSubmitButton button {border-radius: 22px; font-weight: 500;}
[class*="st-key-sec_"] .stButton button[kind="primary"], .stFormSubmitButton button {background: var(--orange);
  border-color: var(--orange); color: #fff;}
[class*="st-key-sec_"] .stButton button[kind="primary"]:hover, .stFormSubmitButton button:hover {background: #FF6448;
  border-color: #FF6448; color: #fff;}
pre {direction: rtl; text-align: right;}
/* כפתורים משניים וקישור לצ'אט בסרגל - שקופים עם מסגרת, כמו "דברו עם נציג" */
.st-key-side .stButton button[kind="secondary"], .st-key-side [data-testid="stPageLink"] a {background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.28); color: #fff; border-radius: 10px; justify-content: center; width: 100%;}
.st-key-side [data-testid="stPageLink"] a {padding: .55rem .9rem; margin: 0;}
@media (min-width: 901px) {
  .st-key-side_actions [data-testid="stElementContainer"], .st-key-side [data-testid="stPageLink"],
  .st-key-side [data-testid="stPageLink"] > div, .st-key-side [data-testid="stPageLink"] a {width: 100% !important; max-width: none;}
}
.st-key-side [data-testid="stPageLink"] a > div, .st-key-side [data-testid="stPageLink"] a {justify-content: center;}
.st-key-side [data-testid="stPageLink"] a * {color: #fff !important;}
.st-key-side .stButton button[kind="secondary"]:hover, .st-key-side [data-testid="stPageLink"] a:hover {
  background: rgba(255,255,255,.12); border-color: rgba(255,255,255,.5); color: #fff;}
.side-nav a {display: flex; align-items: center; gap: .6rem; padding: .5rem .65rem; border-radius: 8px; color: rgba(255,255,255,.9);
  text-decoration: none; font-size: .95rem;}
.side-nav a:hover {background: rgba(255,255,255,.08); color: #fff;}
.side-nav .material {font-size: 1.2rem; vertical-align: 0;}
/* כניסה */
.st-key-login {max-width: 440px; margin: 8vh auto 0; background: var(--paper); border-radius: 18px; box-shadow: var(--shadow);
  padding: 2rem 2rem 1.6rem; border-top: 4px solid var(--orange);}
.st-key-login [data-testid="stForm"] {border: none; padding: 0;}
.login-h {text-align: center;}
.login-h .material {font-size: 2rem; width: 3.6rem; height: 3.6rem; border-radius: 14px; background: var(--orange-soft);
  display: inline-grid; place-items: center; vertical-align: 0;}
.login-h h2 {font-size: 1.4rem; font-weight: 700; color: var(--blue); margin: .7rem 0 .2rem; padding: 0;}
.login-h p {color: var(--gray); margin: 0 0 .8rem;}
@media (max-width: 900px) {
  .st-key-side [data-testid="stPageLink"] a p {display: none;}
  .st-key-side [data-testid="stPageLink"] a {padding: .45rem .6rem;}
  .st-key-side [data-testid="stPageLink"], .st-key-side [data-testid="stPageLink"] > div {width: auto;}
  .st-key-side_actions {align-items: center;}
  .st-key-side [data-testid="stPageLink"], .st-key-side [data-testid="stPageLink"] > div {margin: 0; padding: 0;}
  [class*="st-key-sec_"] {padding: 1rem;}
  .page-h h1 {font-size: 1.5rem;}
}
""")


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
        st.container(key="login").error("יותר מדי ניסיונות שגויים. אפשר לנסות שוב בעוד כמה דקות.")
        st.stop()
    box = st.container(key="login")
    box.markdown('<div class="login-h"><span class="material">lock</span><h2>כניסת מנהל</h2>'
                 '<p>העמוד מיועד לצוות בלבד</p></div>', unsafe_allow_html=True)
    with box.form("login_form", border=False):
        pw = st.text_input("סיסמת מנהל", type="password")
        ok = st.form_submit_button("כניסה", use_container_width=True)
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
        box.error("סיסמה שגויה.")
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
    """בלי תו פתיחה שאקסל מפרש כנוסחה (=, +, -, @). מרכאות ופסיקים - csv.writer מטפל בהם."""
    return "'" + text if text[:1] in "=+-@" else text


def gaps_csv(gaps):
    """CSV שאקסל פותח נכון בעברית: utf-8 עם BOM, כותרות בעברית, תאריך ושעה בעמודות נפרדות."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["תאריך", "שעה", "השאלה", "מה חיפשנו באתר"])
    for g in gaps:
        day, _, hour = g.get("at", "").partition("T")
        w.writerow([day, hour[:5], _csv_safe(g["question"]), _csv_safe(g.get("search_query", ""))])
    return buf.getvalue().encode("utf-8-sig")


STOP = set("של על את עם מה איך כמה אם יש לי זה זו אני אפשר האם או גם כל לא כן מי למה מתי איפה בין אצלכם שלי "
           "ביטוח הפניקס".split())

# ---------------------------------------------------------------- עמוד
SECTIONS = {"data": ("database", "המידע שהבוט עונה ממנו", "המידע"),
            "health": ("monitor_heart", "בדיקת תקינות", "בדיקת תקינות"),
            "refresh": ("sync", "רענון המידע מהאתר", "רענון המידע"),
            "gaps": ("radar", 'מכ"ם פערים: מה לקוחות שואלים ולא מוצאים באתר', 'מכ"ם פערים'),
            "feedback": ("thumbs_up_down", "משוב לקוחות: עזרתי?", "משוב לקוחות")}


def section(key):
    """כרטיס לבן לכל נושא, עם עוגן לקישור מסרגל הצד."""
    icon, title, _ = SECTIONS[key]
    box = st.container(key=f"sec_{key}")
    box.markdown(f'<div class="anchor" id="sec-{key}"></div><div class="sec-h"><span class="material">{icon}</span>'
                 f'<h3>{html.escape(title)}</h3></div>', unsafe_allow_html=True)
    return box


def nice_time(value):
    """2026-10-20T10:50:14+00:00 -> 20/10/2026 13:50 (שעון ישראל)."""
    try:
        when = datetime.fromisoformat(str(value))
        if when.tzinfo:
            when = when.astimezone(ZoneInfo("Asia/Jerusalem"))
        return when.strftime("%d/%m/%Y %H:%M") if "T" in str(value) else when.strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


st.set_page_config(page_title="הפניקס | ניהול הבוט")
logged_in = bool(st.session_state.get("admin"))
m = manifest()
with st.container(key="side"):
    brand("ניהול הבוט", "הפניקס · העוזר הדיגיטלי")
    with st.container(key="side_actions"):
        st.page_link("views/chat.py", label="חזרה לצ'אט", icon=":material/forum:")
        if logged_in and st.button("יציאה", key="logout", icon=":material/logout:", use_container_width=True):
            st.session_state.admin = False
            st.rerun()
    if logged_in:
        with st.container(key="side_more"):
            links = "".join(f'<a href="#sec-{k}"><span class="material">{icon}</span><span>{html.escape(short)}</span></a>'
                            for k, (icon, _, short) in SECTIONS.items())
            st.markdown(f'<div class="side-label">בעמוד הזה</div><nav class="side-nav">{links}</nav>'
                        f'<div class="side-foot">האינדקס נבנה ב-{html.escape(nice_time(m.get("built_at", "-")))}</div>',
                        unsafe_allow_html=True)

if admin_password() is None:
    st.warning("עמוד הניהול סגור: לא הוגדרה סיסמת מנהל (ADMIN_PASSWORD ב-.env או ב-Secrets).")
    st.stop()
if not logged_in:
    login()

st.markdown('<div class="page-h"><h1>ניהול הבוט</h1><span>מצב המידע, תקינות, ומה לקוחות מחפשים ולא מוצאים</span></div>',
            unsafe_allow_html=True)

# ---------- מצב המידע ----------
with section("data"):
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="card"><div class="big">{m.get("pages", "-")}</div><div class="muted">עמודים מהאתר</div></div>',
                unsafe_allow_html=True)
    c2.markdown(f'<div class="card"><div class="big">{m.get("chunks", "-")}</div><div class="muted">פסקאות באינדקס</div></div>',
                unsafe_allow_html=True)
    c3.markdown(f'<div class="card"><div class="big">{html.escape(nice_time(m.get("newest_crawl", "-")))}</div>'
                f'<div class="muted">נאסף לאחרונה</div></div>', unsafe_allow_html=True)
    st.caption(f"האינדקס נבנה ב-{nice_time(m.get('built_at', '-'))} · מודל ההטמעה {m.get('model', '-')}")


# ---------- בדיקת תקינות ----------
with section("health"):
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
with section("refresh"):
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
with section("gaps"):
    gaps = load_gaps()
    if not gaps:
        st.write("אין כרגע שאלות פתוחות. כל שאלה שהבוט עונה עליה \"לא מצאתי\" תופיע כאן - בלי פרטים מזהים.")
    else:
        st.write(("שאלה אחת לא נענתה. " if len(gaps) == 1 else f"{len(gaps)} שאלות לא נענו. ") + "נושאים שחוזרים הם רמז למידע שכדאי להוסיף לאתר. "
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
        st.download_button("הורדת כל השאלות (Excel / CSV)", gaps_csv(gaps), file_name="שאלות-שלא-נענו.csv", mime="text/csv")
        with st.expander("ניקוי כל הרשימה"):
            sure = st.checkbox("כן, למחוק את כל השאלות שלא נענו (אי אפשר לשחזר)", key="sure_gaps")
            if st.button("מחיקת הרשימה", disabled=not sure):
                clear_gaps()
                st.rerun()


# ---------- משוב לקוחות ----------
with section("feedback"):
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

"""
שפת העיצוב המשותפת לצ'אט ולעמוד המנהל: צבעי הפניקס, גופן, וסרגל הצד הכחול (בטלפון - פס עליון).
סרגל הצד הוא st.container(key="side") ובתוכו side_actions (כפתורים) ו-side_more (מוסתר בטלפון).
"""
import streamlit as st


THEME_CSS = """
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
.material {font-family: 'Material Symbols Rounded'; font-size: 1.05rem; vertical-align: -3px; color: var(--orange);}

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
  [data-testid="stMarkdownContainer"]:has(> .brand) {margin-bottom: 0 !important;}
  .brand b {font-size: .95rem; white-space: nowrap;} .brand span {display: none;}
  .st-key-side_actions {flex-direction: row; margin: 0; width: auto !important; flex: none;}
  .st-key-side_actions [data-testid="stElementContainer"] {width: auto !important;}
  .st-key-side .stButton button p, .st-key-side .stLinkButton a p {display: none;}
  .st-key-side .stButton button, .st-key-side .stLinkButton a {padding: .45rem .6rem;}
}

"""

CHAT_ICON = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 '
             '20.5l1.4-4.9A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/></svg>')


def apply_theme(extra_css=""):
    st.markdown(f"<style>{THEME_CSS}{extra_css}</style>", unsafe_allow_html=True)


def brand(title, subtitle):
    st.markdown(f'<div class="brand"><div class="dot">{CHAT_ICON}</div><div><b>{title}</b>'
                f'<span>{subtitle}</span></div></div>', unsafe_allow_html=True)

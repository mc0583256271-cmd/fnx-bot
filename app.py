"""
נקודת הכניסה: מנתב בין שני עמודים.
  /       הצ'אט ללקוחות (views/chat.py)
  /admin  עמוד המנהל, בסיסמה (views/admin.py) - לא מופיע בתפריט ולא מקושר מהצ'אט

הרצה (מתיקיית הפרויקט):
  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="הפניקס | עוזר דיגיטלי", page_icon="💬", layout="wide",
                   initial_sidebar_state="collapsed")
page = st.navigation([st.Page("views/chat.py", title="הפניקס | עוזר דיגיטלי", default=True),
                      st.Page("views/admin.py", title="ניהול הבוט", url_path="admin")],
                     position="hidden")
page.run()

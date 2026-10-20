"""
שלב 5: שאלות גבול שמטופלות לפני החיפוש.

כרגע: הודעות שיחה (תודה, שלום, ביי...) - תשובה ידידותית מיד, בלי חיפוש ובלי מודל.
(שאלות על פוליסה אישית וייעוץ מטופלות בהוראות למודל ב-core/answer.py.)
"""
import re

_WORDS = r"(תודה|תודה רבה|רבה|תנקס|שלום|היי|הי|הלו|בוקר טוב|ערב טוב|לילה טוב|צהריים טובים|ביי|להתראות|יום טוב|" \
         r"מעולה|מצוין|אחלה|סבבה|אוקיי|אוקי|אוקיי תודה|הבנתי|ברור|נהדר|יופי|כל הכבוד|ok|thanks|thank you|hi|hello|bye)"
_SMALL_TALK = re.compile(rf"^\s*({_WORDS}[\s,!.?:)(]*)+$", re.IGNORECASE)

THANKS = "בשמחה! אם יש עוד שאלה על ביטוח, תביעות, פנסיה או חיסכון - אני כאן."
GREETING = "שלום! אפשר לשאול אותי על ביטוח, תביעות, פנסיה, חיסכון והלוואות - אענה לפי המידע באתר הפניקס."
BYE = "להתראות! אם תצטרכו עוד משהו, אני כאן."


def small_talk_reply(message):
    """אם ההודעה היא רק נימוס/ברכה - מחזיר תשובה מתאימה. אחרת None (ממשיכים לחיפוש)."""
    text = message.strip()
    if len(text) > 40 or not _SMALL_TALK.match(text):
        return None
    if re.search(r"ביי|להתראות|לילה טוב|bye", text, re.IGNORECASE):
        return BYE
    if re.search(r"שלום|היי|הי|הלו|בוקר טוב|ערב טוב|צהריים טובים|hi|hello", text, re.IGNORECASE) \
            and not re.search(r"תודה|thank", text, re.IGNORECASE):
        return GREETING
    return THANKS

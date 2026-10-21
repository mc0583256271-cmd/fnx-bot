"""
שכבת האימות ("כל תשובה חייבת להוכיח את עצמה").

אחרי שהמודל כתב תשובה, הקוד - לא המודל - בודק אותה מול הפסקאות שנשלפו מהאתר:
1. ציטוטים: המודל מצרף 1-4 ציטוטים שמוכיחים את התשובה. כל ציטוט נבדק מילה במילה מול הפסקה
   שהוא טוען שממנה לקח. ציטוט שלא נמצא - לא מוצג (המודל לא יכול "להמציא ראיה").
2. מספרים: כל מספר בתשובה (סכום, אחוז, טלפון, תאריך, מספר ימים) חייב להופיע בפסקאות.
   מספר שלא מופיע = כנראה המצאה או טעות חישוב -> התשובה לא מוצגת ("לא מצאתי").
"""
import re

EVIDENCE_HEAD = re.compile(r"^\s*\**\s*EVIDENCE\s*:?\s*\**\s*$", re.IGNORECASE | re.MULTILINE)
_EVIDENCE_ROW = re.compile(r"^\s*[-*]?\s*\[?(\d+)\]?\s*[|:]\s*(.+?)\s*$")
_QUOTES = "\"'“”„״׳`"


def normalize(text):
    """השוואה סלחנית רק לעיצוב: בלי הדגשות, מרכאות אחידות, רווחים אחידים."""
    text = text.replace("\xa0", " ").replace("**", "").replace("__", "")
    text = re.sub(r"[“”„״]", '"', text)
    text = re.sub(r"[‘’׳`]", "'", text)
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"\s*\n\s*[+*-]?\s*", " ", text)  # שורות ורשימות בפסקה נקראות כמשפט רצוף
    return re.sub(r"\s+", " ", text).strip()


def parse_evidence(block):
    """שורות "מספר | "ציטוט"" -> [(מספר, ציטוט)]."""
    rows = []
    for line in block.splitlines():
        m = _EVIDENCE_ROW.match(line)
        if m:
            quote = m.group(2).strip().strip(_QUOTES).strip()
            if len(quote) >= 8:
                rows.append((int(m.group(1)), quote))
    return rows


def _found(quote, passage):
    q, p = normalize(quote).strip(" ."), normalize(passage)
    if q in p:
        return True
    parts = [x.strip(" .") for x in re.split(r"\.\.\.|…", q) if len(x.strip(" .")) >= 8]
    return len(parts) > 1 and all(x in p for x in parts)  # ציטוט עם השמטה ("...") - כל חלק נבדק


def verify_quotes(rows, hits):
    """מחזיר רק ציטוטים שנמצאו מילה במילה בפסקה שצוינה (עד 4, בלי כפילויות)."""
    out, seen = [], set()
    for n, quote in rows:
        if not 1 <= n <= len(hits) or quote in seen:
            continue
        h = hits[n - 1]
        if _found(quote, h["text"]):
            seen.add(quote)
            out.append({"n": n, "quote": quote, "title": h["title"], "url": h["url"]})
    return out[:4]


def _numbers(text, answer=False):
    if answer:
        text = re.sub(r"(?m)^\s*\d+\.\s", " ", text)  # מספור שלבים (1. 2. 3.) אינו טענה
    return {_canon(x) for x in re.findall(r"\d[\d,.]*", text)}


def _canon(x):
    """צורה אחידה: בלי פסיקי אלפים, ובלי אפסים מובילים במספר שלם ובתאריך (02.10.2025 = 2.10.2025)."""
    parts = x.replace(",", "").rstrip(".").split(".")
    if len(parts) in (1, 3):
        parts = [part.lstrip("0") or "0" for part in parts]
    return ".".join(parts)


# מספרים קטנים כתובים באתר לעתים במילים ("עד גיל שמונה", "שש שנים") - גם זה נחשב "מופיע"
_WORDS = {"0": "אפס|ללא", "1": "אחד|אחת", "2": "שניים|שתיים|שני|שתי", "3": "שלוש|שלושה|שלושת", "4": "ארבע|ארבעה|ארבעת",
          "5": "חמש|חמישה|חמשת", "6": "שש|שישה|ששת", "7": "שבע|שבעה|שבעת", "8": "שמונה|שמונת", "9": "תשע|תשעה|תשעת",
          "10": "עשר|עשרה|עשרת", "12": "שתים עשרה|שנים עשר", "24": "24"}


def unverified_numbers(answer_text, hits, question=""):
    """המספרים בתשובה שלא מופיעים באף פסקה שנשלחה למודל (בספרות, או במילים למספרים קטנים).
    מספר שהלקוח עצמו כתב בשאלה ("פוטרתי אחרי 5 שנים") מותר לחזור עליו."""
    have, words = _numbers(question), " ".join(h["text"] for h in hits)
    for h in hits:
        have |= _numbers(h["text"]) | _numbers(h["title"])
    missing = []
    for n in sorted(_numbers(answer_text, answer=True)):
        if n in have:
            continue
        if n in _WORDS and re.search(rf"(?<![א-ת])[ובלמשה]?({_WORDS[n]})(?![א-ת])", words):
            continue
        missing.append(n)
    return missing


def numbers_in(answer_text):
    return len(_numbers(answer_text, answer=True))

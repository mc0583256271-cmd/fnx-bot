"""
"מכ"ם פערים": שאלות שהבוט לא מצא להן תשובה באתר נשמרות (בלי השיחה ובלי פרטים מזהים),
כדי שהמנהל יראה מה לקוחות מחפשים ולא מוצאים - ויוכל להשלים את התוכן באתר.
"""
import json
import re
import threading
from datetime import datetime
from pathlib import Path

GAPS_FILE = Path(__file__).resolve().parent.parent / "data" / "gaps.jsonl"
FEEDBACK_FILE = Path(__file__).resolve().parent.parent / "data" / "feedback.jsonl"
_lock = threading.Lock()


def mask(text):
    """מסתיר פרטים מזהים: מיילים, ומספרים ארוכים (ת"ז, טלפון, מספר פוליסה)."""
    text = re.sub(r"\S+@\S+", "[מייל]", text)
    return re.sub(r"\d[\d\- ]{4,}\d", "[מספר]", text)


def log_gap(question, search_query=None, reason=None):
    try:
        row = {"at": datetime.now().isoformat(timespec="seconds"), "question": mask(question)[:300],
               "search_query": mask(search_query or question)[:300], "reason": (reason or "")[:80]}
        with _lock, GAPS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # רישום הפערים לא יפיל את הצ'אט


def load_gaps():
    if not GAPS_FILE.exists():
        return []
    rows = []
    for line in GAPS_FILE.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _same(a, b):
    return re.sub(r"[?!.,\s]+", " ", a).strip() == re.sub(r"[?!.,\s]+", " ", b).strip()


def remove_question(question):
    """המנהל סימן שאלה כ"טופלה" (למשל הוסיפו מידע לאתר): כל המופעים שלה יורדים מהרשימה."""
    rows = [r for r in load_gaps() if not _same(r["question"], question)]
    _rewrite(GAPS_FILE, rows)


def clear_gaps():
    _rewrite(GAPS_FILE, [])


def _rewrite(path, rows):
    with _lock:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        tmp.replace(path)


# ---------- משוב 👍 / 👎 ----------
def log_feedback(question, answer, status, helpful):
    """לקוח לחץ 👍 או 👎 על תשובה. נשמר בלי פרטים מזהים, כדי שהמנהל יראה אילו תשובות לא עזרו."""
    try:
        row = {"at": datetime.now().isoformat(timespec="seconds"), "helpful": bool(helpful),
               "question": mask(question or "")[:300], "answer": mask(answer or "")[:400], "status": status}
        with _lock, FEEDBACK_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_feedback():
    if not FEEDBACK_FILE.exists():
        return []
    out = []
    for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def clear_feedback():
    _rewrite(FEEDBACK_FILE, [])

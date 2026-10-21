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

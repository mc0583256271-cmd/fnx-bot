"""
הטמעות (embeddings) של Gemini - קוד משותף לבניית האינדקס, לחיפוש ולבדיקות.

- המפתח נקרא מ-GEMINI_API_KEY (משתנה סביבה או קובץ .env). לעולם לא מודפס.
- כל וקטור נשמר במטמון לפי טביעת האצבע (SHA1) של הטקסט שהוטמע.
  טקסט שלא השתנה לא נשלח שוב לגוגל - כך רענון עולה רק מה שהשתנה.
- מגבלות שנמדדו בחשבון החינמי: כל טקסט נספר כבקשה (גם בתוך מנה של 100),
  כ-100 בדקה וכ-1,000 ביום. ההרצה נעצרת יפה ושומרת, וממשיכה בפעם הבאה.
"""
import hashlib
import os
import time
from pathlib import Path

try:
    import truststore  # אישורי SSL של Windows (סינון אינטרנט) - כמו ב-crawl.py
    truststore.inject_into_ssl()
except ImportError:
    pass
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

MODEL = "gemini-embedding-2"
DIM = 3072            # מה שמבקשים מגוגל ושומרים במטמון
INDEX_DIM = 768       # מה שהאינדקס משתמש בו (נבדק: איכות זהה ל-3072, קטן פי 4)
CACHE_DIR = ROOT / "data" / "emb_cache" / f"{MODEL}_{DIM}"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:batchEmbedContents"
BATCH_SIZE = 100      # כמה טקסטים בבקשה אחת. יורד אוטומטית אם השרת מסרב
MAX_429_IN_A_ROW = 10 # אחרי כך עוצרים ושומרים, וממשיכים בהרצה הבאה

# הפורמט שגוגל ממליצה עליו ל-gemini-embedding-2 (אין task_type, יש קידומת)
QUERY_FORMATS = {
    "search": "task: search result | query: {q}",
    "qa": "task: question answering | query: {q}",
}
QUERY_FORMAT = "search"  # זה שנבחר לבוט (בבדיקות: זהה ל-qa)


def doc_format(chunk):
    return f"title: {chunk['title']} | text: {chunk['text']}"

def query_format(question, fmt=QUERY_FORMAT):
    return QUERY_FORMATS[fmt].format(q=question)


class Stop(Exception):
    """תקלה שבגללה עוצרים (ההטמעות שכבר התקבלו שמורות)."""


# ---------- מפתח ----------
def load_key(name="GEMINI_API_KEY"):
    """קורא מפתח ממשתנה סביבה או מקובץ .env (השורה האחרונה שלא בהערה). לעולם לא מודפס."""
    key = os.environ.get(name, "")
    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith(name + "="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key or key == "your-key-here":
        raise Stop(f"לא נמצא {name} בקובץ .env")
    return key


# ---------- מטמון ----------
def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def load_cache():
    cache = {}
    for f in sorted(CACHE_DIR.glob("part_*.npz")):
        data = np.load(f)
        for h, v in zip(data["keys"], data["vecs"]):
            cache[str(h)] = v
    return cache

def save_part(keys, vecs):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    numbers = [int(f.stem.split("_")[1]) for f in CACHE_DIR.glob("part_*.npz")]
    n = max(numbers, default=-1) + 1  # תמיד מספר חדש, גם אם קובץ באמצע נמחק
    tmp = CACHE_DIR / f"tmp_{n:05d}.npz"
    np.savez(tmp, keys=np.array(keys), vecs=np.array(vecs, dtype=np.float32))
    tmp.replace(CACHE_DIR / f"part_{n:05d}.npz")  # כתיבה "אטומית": אין קובץ חצי-שמור


# ---------- קריאה ל-Gemini ----------
def parse_429(resp):
    """מחזיר (כמה לחכות, שם המכסה) מתוך תשובת 429 של גוגל."""
    delay, quota = 30.0, "?"
    try:
        for d in resp.json()["error"].get("details", []):
            if d.get("@type", "").endswith("RetryInfo"):
                delay = float(d.get("retryDelay", "30s").rstrip("s"))
            if d.get("@type", "").endswith("QuotaFailure"):
                quota = d["violations"][0].get("quotaId", "?")
    except Exception:
        pass
    return delay, quota

def call_api(session, key, texts):
    """בקשה אחת. מחזיר ('ok', וקטורים) / ('wait', שניות, מכסה) / ('smaller', הודעה)."""
    body = {"requests": [{"model": f"models/{MODEL}",
                          "content": {"parts": [{"text": t}]},
                          "outputDimensionality": DIM} for t in texts]}
    for attempt in range(4):
        try:
            r = session.post(API_URL, json=body, headers={"x-goog-api-key": key}, timeout=120)
        except requests.RequestException as e:
            if attempt == 3:
                hint = " (אישור SSL: ודאי ש-truststore מותקן)" if isinstance(e, requests.exceptions.SSLError) else ""
                raise Stop(f"בעיית רשת מול Gemini: {type(e).__name__}{hint}")
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                vecs = [e["values"] for e in r.json()["embeddings"]]
            except Exception:
                raise Stop("Gemini החזיר תשובה לא צפויה (ייתכן דף חסימה של סינון): "
                           + r.text[:150].replace("\n", " "))
            if len(vecs) != len(texts) or any(len(v) != DIM for v in vecs):
                raise Stop(f"קיבלנו {len(vecs)} וקטורים במקום {len(texts)}, או בגודל לא נכון")
            return ("ok", vecs)
        if r.status_code == 429:
            delay, quota = parse_429(r)
            return ("wait", delay, quota)
        if r.status_code == 400 and len(texts) > 1:
            return ("smaller", r.text[:200].replace("\n", " "))
        if r.status_code in (401, 403):
            raise Stop(f"Gemini סירב ({r.status_code}): המפתח לא תקין, לא מופעל, או חסום ברשת. "
                       + r.text[:150].replace("\n", " "))
        if r.status_code >= 500 and attempt < 3:
            time.sleep(10 * (attempt + 1))
            continue
        raise Stop(f"Gemini החזיר {r.status_code}: " + r.text[:200].replace("\n", " "))
    raise Stop("Gemini לא ענה אחרי כמה ניסיונות")

def embed_all(texts, cache, key, label):
    """מטמיע את כל הטקסטים שעוד לא במטמון. שומר אחרי כל בקשה מוצלחת. מחזיר כמה הוטמעו."""
    missing = list(dict.fromkeys(t for t in texts if text_hash(t) not in cache))
    if not missing:
        print(f"   {label}: הכל כבר במטמון ({len(texts)})")
        return 0
    print(f"   {label}: צריך להטמיע {len(missing)} מתוך {len(texts)}")
    session = requests.Session()
    batch, done, in_a_row = BATCH_SIZE, 0, 0
    while done < len(missing):
        part = missing[done:done + batch]
        result = call_api(session, key, part)
        if result[0] == "ok":
            keys = [text_hash(t) for t in part]
            save_part(keys, result[1])
            for k, v in zip(keys, result[1]):
                cache[k] = np.array(v, dtype=np.float32)
            done += len(part)
            in_a_row = 0
            print(f"      {done}/{len(missing)}")
        elif result[0] == "wait":
            _, delay, quota = result
            in_a_row += 1
            if "PerDay" in quota:
                raise Stop(f"נגמרה המכסה היומית ({quota}). מחר מריצים שוב וממשיכים מ-{done}")
            if in_a_row > MAX_429_IN_A_ROW:
                raise Stop(f"יותר מדי סירובי קצב ברצף ({quota}). מריצים שוב מאוחר יותר")
            if "Token" in quota:  # מגבלת טוקנים לדקה: מנות קטנות יותר עוזרות. מגבלת בקשות: לא
                batch = max(5, batch // 2)
            print(f"      מגבלת קצב ({quota}). מחכים {delay:.0f} שניות, ממשיכים במנות של {batch}")
            time.sleep(delay + 1)
        else:
            if batch <= 1:
                raise Stop("Gemini סירב גם לטקסט בודד: " + result[1])
            batch = max(1, batch // 2)
            print(f"      הבקשה גדולה מדי, מקטינים למנות של {batch}")
    return done


def normalize(m):
    return m / np.linalg.norm(m, axis=-1, keepdims=True)

def to_index_dim(vectors):
    """קיצור ל-768 ונרמול מחדש - בדיוק כמו שנבדק בהשוואה."""
    return normalize(np.asarray(vectors, dtype=np.float32)[..., :INDEX_DIM])

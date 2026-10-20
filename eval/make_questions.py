"""
בניית סט שאלות בדיקה גדול ובלתי תלוי (eval/questions_full.json).

למה: 31 שאלות שאני כתבתי ובחרתי להן עמודים - מדגם קטן ומוטה.
כאן העמודים נבחרים בהגרלה, ומודל שפה כותב את השאלות.

קבוצות:
  אקראי   - 100 עמודים אקראיים מכל האתר. מודל שפה כותב שאלה של לקוח לכל עמוד.
  מסלולים - 15 עמודי מסלולי השקעה (כמעט זהים זה לזה) - החולשה שמצאנו.
  שמות    - עמודי מוצרים עם שם באנגלית (ריסק WELL, BlackRock...) - החולשה השנייה.
  ידני    - 31 השאלות הקודמות (eval/questions.json).
  בלי תשובה - 20 שאלות שהתשובה עליהן לא באתר (נבדק בחיפוש בנתונים).

בדיקות על כל שאלה שהמודל כותב:
  - הציטוט שהמודל צירף כתשובה באמת מופיע בעמוד (אחרת השאלה נפסלת).
  - השאלה לא מעתיקה 4 מילים ברצף מהעמוד (אחרת היא קלה מדי לחיפוש מילים).

הרצה:  python eval/make_questions.py
אפשר לעצור ולהריץ שוב: שאלות שכבר נוצרו נשמרות ב-eval/questions_auto.jsonl.
"""
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_search as cs  # מפתח, SSL, ומבנה התיקיות - משותפים

ROOT = cs.ROOT
PAGES_FILE = ROOT / "data" / "pages.jsonl"
AUTO_FILE = ROOT / "eval" / "questions_auto.jsonl"
OUT_FILE = ROOT / "eval" / "questions_full.json"

GEN_MODEL = "gemini-2.5-flash"
GEN_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEN_MODEL}:generateContent"
SEED = 2026
N_RANDOM = 100
N_TRACKS = 15
MAX_PAGE_WORDS = 2500
MAX_COPY_RUN = 4  # 4 מילים ברצף מהעמוד = העתקה

TRACK_URL = re.compile(r"/tz[a-z]*/\d+/")
NAME_TITLE = re.compile(r"[A-Za-z]{3,}")

PROMPT = """אתה לקוח של חברת הביטוח הפניקס. לפניך עמוד מאתר החברה.
כתוב שאלה אחת שלקוח אמיתי היה שואל בצ'אט של שירות הלקוחות, שהתשובה עליה נמצאת בעמוד הזה.

כללים:
- עברית יומיומית, 5 עד 20 מילים, כמו בהודעה בוואטסאפ.
- אל תעתיק את הכותרת או משפטים מהעמוד. נסח במילים שלך, כמו לקוח שלא קרא את העמוד.
- השאלה צריכה להיות ספציפית לעמוד הזה, ולא שאלה כללית שעשרות עמודים עונים עליה.
{extra}- answer_quote: ציטוט קצר (עד 25 מילים) מתוך העמוד שעונה על השאלה, מועתק אות באות.

החזר JSON בלבד: {{"question": "...", "answer_quote": "..."}}

כותרת העמוד: {title}

תוכן העמוד:
{content}"""
NAME_EXTRA = "- השאלה חייבת להזכיר את שם המוצר, כמו שלקוח ישראלי היה כותב אותו (לפעמים באותיות עבריות).\n"

UNANSWERABLE_NEW = [  # כל אחת נבדקה בחיפוש בנתונים: אין עליה תשובה באתר
    "מה שעות הפתיחה של הסניף שלכם בבאר שבע?",
    "מה מספר הפוליסה שלי?",
    "האם התביעה ששלחתי בשבוע שעבר אושרה?",
    "כמה עולה מניה של הפניקס היום?",
    "באיזה בנק הכי כדאי לקחת משכנתא?",
    "מה התחזית למזג האוויר בטיסה שלי ליוון?",
    "איך מזמינים תור לטסט שנתי במכון רישוי?",
    "מה שעות הפתיחה של מוסך מורשה בחולון?",
    "כמה עולה כרטיס טיסה לאילת?",
    "איך מגישים ערעור על דוח חניה?",
]


def norm(text):
    text = re.sub(r"[*#_|>\[\]()`]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def words(text):
    return re.findall(r"\w+", text)

def longest_copy(question, page_text):
    """הרצף הארוך ביותר של מילים מהשאלה שמופיע כמו שהוא בעמוד."""
    q, page = words(question), " " + " ".join(words(page_text)) + " "
    best = 0
    for i in range(len(q)):
        for j in range(i + best + 1, len(q) + 1):
            if " " + " ".join(q[i:j]) + " " in page:
                best = j - i
            else:
                break
    return best


def generate(session, key, page, extra=""):
    content = " ".join(page["content_md"].split()[:MAX_PAGE_WORDS])
    body = {"contents": [{"parts": [{"text": PROMPT.format(extra=extra, title=page["title"], content=content)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7,
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    for attempt in range(6):
        try:
            r = session.post(GEN_URL, json=body, headers={"x-goog-api-key": key}, timeout=120)
        except requests.RequestException as e:
            if attempt == 5:
                raise cs.Stop(f"בעיית רשת: {type(e).__name__}")
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                data = json.loads(text)
                return data["question"].strip(), data["answer_quote"].strip()
            except Exception:
                return None, None  # תשובה לא תקינה - נרשם כנפסל
        if r.status_code == 429:
            delay, quota = cs.parse_429(r)
            if "PerDay" in quota:
                raise cs.Stop(f"נגמרה המכסה היומית של {GEN_MODEL} ({quota})")
            print(f"      מגבלת קצב ({quota}), מחכים {delay:.0f} שניות")
            time.sleep(delay + 1)
            continue
        if r.status_code >= 500:
            time.sleep(10 * (attempt + 1))
            continue
        raise cs.Stop(f"{GEN_MODEL} החזיר {r.status_code}: " + r.text[:200].replace("\n", " "))
    raise cs.Stop("יותר מדי ניסיונות כושלים")


def main():
    pages = [json.loads(line) for line in PAGES_FILE.open(encoding="utf-8")]
    chunk_urls = {json.loads(line)["url"] for line in cs.CHUNKS_FILE.open(encoding="utf-8")}
    pages = sorted((p for p in pages if p["url"] in chunk_urls), key=lambda p: p["url"])
    rng = random.Random(SEED)

    tracks = [p for p in pages if TRACK_URL.search(p["url"])]
    names = [p for p in pages if NAME_TITLE.search(p["title"]) and "תנאי שימוש" not in p["title"]
             and "ממליצים" not in p["title"] and "Phishing" not in p["title"]]
    others = [p for p in pages if p not in names]
    # עודף של 20%: חלק מהשאלות ייפסלו בבדיקות
    plan = [("אקראי", p) for p in rng.sample(others, int(N_RANDOM * 1.2))] + [("שמות", p) for p in names]

    done = {}
    if AUTO_FILE.exists():
        for line in AUTO_FILE.open(encoding="utf-8"):
            row = json.loads(line)
            done[(row["group"], row["url"])] = row

    key, session = cs.load_key(), requests.Session()
    print(f"📝 {len(plan)} עמודים לשאלות ({len(done)} כבר מוכנים)")
    try:
        with AUTO_FILE.open("a", encoding="utf-8") as out:
            for group, page in plan:
                if (group, page["url"]) in done:
                    continue
                if group == "אקראי" and sum(1 for r in done.values()
                                            if r["group"] == "אקראי" and r["status"] == "ok") >= N_RANDOM:
                    continue
                q, quote = generate(session, key, page, NAME_EXTRA if group == "שמות" else "")
                row = {"group": group, "url": page["url"], "title": page["title"], "q": q, "quote": quote}
                if not q or not quote:
                    row["status"] = "תשובה לא תקינה מהמודל"
                elif norm(quote) not in norm(page["content_md"]):
                    row["status"] = "הציטוט לא נמצא בעמוד"
                elif longest_copy(q, page["title"] + " " + page["content_md"]) >= MAX_COPY_RUN:
                    row["status"] = "העתקה מהעמוד"
                else:
                    row["status"] = "ok"
                done[(group, page["url"])] = row
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(f"   {len(done):3} {row['status'][:12]:12} | {group:6} | {page['url'].split('.co.il')[1][:50]}")
    except cs.Stop as e:
        print(f"\n🛑 {e}\n   מריצים שוב מאוחר יותר - ממשיך מאיפה שעצר.")
        return

    # ---------- הרכבת הסט המלא ----------
    manual = json.loads(cs.QUESTIONS_FILE.read_text(encoding="utf-8"))
    ok = [r for r in done.values() if r["status"] == "ok"]
    answerable = ([{"q": r["q"], "url": r["url"].split(".co.il")[1], "group": r["group"], "exact": True}
                   for r in ok if r["group"] == "אקראי"][:N_RANDOM]
                  + [{"q": r["q"], "url": r["url"].split(".co.il")[1], "group": r["group"], "exact": True}
                     for r in ok if r["group"] == "שמות"])
    verbs = ["כמה הרוויח {t} מתחילת השנה?", "מה דמי הניהול ב{t}?", "מה התשואה של {t} ב-12 החודשים האחרונים?"]
    for i, p in enumerate(rng.sample(tracks, N_TRACKS)):
        title = re.sub(r"\s+", " ", p["title"]).strip()
        answerable.append({"q": verbs[i % 3].format(t=title), "url": p["url"].split(".co.il")[1], "group": "מסלולים", "exact": True})
    answerable += [dict(a, group="ידני") for a in manual["answerable"]]

    # שאלות בלי תשובה: אסור שיופיעו מילות המפתח שלהן בנתונים (נבדק ידנית, וכאן שוב לוודא)
    unanswerable = manual["unanswerable"] + UNANSWERABLE_NEW

    rejected = {}
    for r in done.values():
        if r["status"] != "ok":
            rejected[r["status"]] = rejected.get(r["status"], 0) + 1
    OUT_FILE.write_text(json.dumps({"_הסבר": __doc__.strip().splitlines()[0],
                                    "answerable": answerable, "unanswerable": unanswerable},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    groups = {}
    for a in answerable:
        groups[a["group"]] = groups.get(a["group"], 0) + 1
    print(f"\n✅ {len(answerable)} שאלות עם תשובה {groups} | {len(unanswerable)} בלי תשובה")
    print(f"   נפסלו: {rejected or 'אף אחת'}")
    print(f"💾 נשמר ל: {OUT_FILE}")


if __name__ == "__main__":
    main()

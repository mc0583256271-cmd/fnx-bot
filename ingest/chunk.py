"""
שלב 2: חיתוך העמודים לפסקאות (chunks)
=======================================
למה בכלל לחתוך?
  בכל שאלה הבוט ישלוף רק כמה פסקאות רלוונטיות ויעביר אותן לג'מיני.
  עמוד שלם ארוך מדי ומכיל כמה נושאים; משפט בודד קצר מדי ואין בו הקשר.
  פסקה של 100-400 מילים על נושא אחד = "יחידת ידע" אידיאלית.

מה הקובץ עושה:
  1. קורא את data/pages.jsonl (הפלט של שלב 1)
  2. מוחק פסקאות משפטיות שחוזרות על עצמן בעשרות עמודים ("החברה עושה מאמצים...")
  3. חותך כל עמוד לפי הכותרות שלו (## / ###) - כך כל פסקה עוסקת בנושא אחד
  4. מאחד קטעים קטנים מדי, ומפצל קטעים ארוכים מדי
  5. מוסיף לראש כל פסקה "כותרת הקשר": מאיזה עמוד ומדור היא הגיעה
  6. שומר ל-data/chunks.jsonl

איך מריצים:
  python ingest/chunk.py
"""

import hashlib
import json
import re
import statistics
from pathlib import Path

DATA_DIR = Path("data")
INPUT_FILE = DATA_DIR / "pages.jsonl"
OUTPUT_FILE = DATA_DIR / "chunks.jsonl"

# גודל פסקה במילים. מצאנו בנתונים שהחציון של קטע בין כותרות הוא 50 מילים בלבד,
# ולכן מאחדים קטעים עד שמגיעים לפחות ל-MIN_WORDS.
MIN_WORDS = 120
MAX_WORDS = 400

# פסקאות משפטיות שחוזרות כמעט בכל עמוד. מצאנו אותן בניתוח הנתונים:
# הראשונה הופיעה ב-181 עמודים! אם לא נמחק, היא תופיע בתוצאות של כל חיפוש.
BOILERPLATE_STARTS = [
    "החברה עושה מאמצים בכדי לוודא",
    "מידע זה הינו כללי אודות",
    "לידיעתך במערכות הפניקס קיים מנגנון",
    "האמור בעמוד זה הינו תמצית בלבד",
    "\\*יודגש, כי אין במפורט בהנחיות אלו",
]

# שורות "מטא" בתחילת מאמרים: תאריך פרסום וזמן קריאה ("* 3 דקות")
META_LINE = re.compile(r"^\* ?(\d+(\.\d+)? דקות|דקה אחת|\d{1,2} ב\S+ \d{4})$")

HEADING = re.compile(r"^(#{1,5}) (.+)$")

# כותרת שהגיעה בתוך פריט ברשימה, למשל "6. ### חוק להרתעה נגד שיכרות"
LIST_HEADING = re.compile(r"^\s*(?:[*+-]|\d+\.)\s+(#{1,5} .+)$")


def words(text):
    return len(text.split())


def clean_page(text):
    """מוחקת פסקאות משפטיות חוזרות ושורות של תאריך/זמן קריאה."""
    paragraphs = []
    for para in text.split("\n\n"):
        stripped = para.strip()
        if not stripped:
            continue
        # המשפט המשפטי מופיע לפעמים בסוף פסקה רגילה - חותכים מהמקום שבו הוא מתחיל
        for start in BOILERPLATE_STARTS:
            position = stripped.find(start)
            if position != -1:
                stripped = stripped[:position].strip()
        if not stripped:
            continue
        # במאמרים התאריך וזמן הקריאה מופיעים יחד: "* 25 בינואר 2022\n* 3 דקות"
        lines = [line for line in stripped.split("\n") if not META_LINE.match(line.strip())]

        # כותרת שמסתתרת באמצע פסקה (בתוך רשימה) - פותחת פסקה חדשה משלה
        block = []
        for line in lines:
            hidden = LIST_HEADING.match(line)
            if hidden:
                if block:
                    paragraphs.append("\n".join(block))
                block = [hidden.group(1)]
            else:
                block.append(line)
        if block:
            paragraphs.append("\n".join(block))
    return paragraphs


def split_long_paragraph(para):
    """
    פסקה אחת ארוכה מ-MAX_WORDS (בדרך כלל טבלת תשואות) - מפצלים לפי שורות.
    בטבלאות האלה כל שורה מתארת את עצמה ("תשואה לשנת 2025 6.03%"), אז אפשר לפצל בלי לאבד משמעות.
    """
    if words(para) <= MAX_WORDS:
        return [para]
    pieces, current = [], []
    for line in para.split("\n"):
        if current and words("\n".join(current)) + words(line) > MAX_WORDS:
            pieces.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        pieces.append("\n".join(current))
    return pieces


def split_by_headings(paragraphs):
    """
    מחלקת את רשימת הפסקאות לקטעים לפי כותרות.
    לכל קטע שומרים את "שביל הכותרות" שלו, למשל:  שאלות נפוצות > האם ניתן לרכוש אונליין?
    """
    sections = []
    path = {}  # רמת כותרת -> טקסט הכותרת. למשל {2: "שאלות נפוצות", 3: "האם..."}
    current = {"headings": [], "paras": []}

    for para in paragraphs:
        first_line = para.split("\n")[0]
        match = HEADING.match(first_line)
        if match:
            if current["paras"]:
                sections.append(current)
            level, title = len(match.group(1)), match.group(2).strip()
            path = {lvl: t for lvl, t in path.items() if lvl < level}  # כותרת חדשה "סוגרת" את הכותרות שמתחתיה
            path[level] = title
            # רמה 1 (#) היא שם העמוד - הוא כבר בכותרת ההקשר, אז לא חוזרים עליו
            current = {"headings": [path[lvl] for lvl in sorted(path) if lvl > 1], "paras": []}
            rest = para.split("\n", 1)[1].strip() if "\n" in para else ""
            if rest:  # טקסט שבא באותה פסקה מיד אחרי הכותרת
                current["paras"].append(rest)
        else:
            current["paras"].append(para)

    if current["paras"]:
        sections.append(current)
    return sections


def merge_and_split(sections):
    """
    מאחדת קטעים קטנים עם הבאים אחריהם, ומפצלת קטעים ארוכים לפי פסקאות.
    התוצאה: רשימת (שביל-כותרות, טקסט) בגודל MIN_WORDS עד MAX_WORDS בערך.
    """
    chunks = []
    buffer_paras, buffer_headings = [], None

    def flush():
        nonlocal buffer_paras, buffer_headings
        if buffer_paras:
            chunks.append((buffer_headings or [], "\n\n".join(buffer_paras)))
        buffer_paras, buffer_headings = [], None

    for section in sections:
        heading_line = section["headings"][-1] if section["headings"] else None
        paras = [piece for para in section["paras"] for piece in split_long_paragraph(para)]
        # כשמאחדים קטע לתוך פסקה שכבר התחילה, הכותרת שלו נשמרת בתוך הטקסט (כדי לא לאבד אותה)
        if buffer_paras and heading_line:
            paras = [f"**{heading_line}**"] + paras

        for para in paras:
            if buffer_headings is None:
                buffer_headings = section["headings"]
            if buffer_paras and words("\n\n".join(buffer_paras)) + words(para) > MAX_WORDS:
                flush()
                buffer_headings = section["headings"]
            buffer_paras.append(para)

        if words("\n\n".join(buffer_paras)) >= MIN_WORDS:
            flush()

    flush()
    return chunks


def make_chunk(page, headings, body, index):
    """בונה את הכרטיסייה של פסקה אחת, כולל כותרת ההקשר."""
    topic = " > ".join(headings) if headings else ""
    # כותרת ההקשר: בזכותה גם פסקה שכתוב בה רק "יש להגיש תוך 30 יום"
    # תימצא בחיפוש על "תביעת ביטוח דירה" - כי שם העמוד והמדור כתובים בראשה.
    header = f"עמוד: {page['title']} | מדור: {page['breadcrumb']}"
    if topic:
        header += f" | נושא: {topic}"
    chunk_id = hashlib.md5(f"{page['url']}#{index}".encode()).hexdigest()[:12]
    return {
        "chunk_id": chunk_id,
        "url": page["url"],
        "title": page["title"],
        "breadcrumb": page["breadcrumb"],
        "section": page["section"],
        "topic": topic,
        "lastmod": page["lastmod"],
        "crawled_at": page["crawled_at"],
        "word_count": words(body),
        "text": f"{header}\n\n{body}",  # זה מה שייכנס לאינדקס ויישלח לג'מיני
        "body": body,                   # הטקסט המקורי בלבד - לבדיקת ציטוטים בהמשך
    }


def main():
    pages = [json.loads(line) for line in INPUT_FILE.read_text(encoding="utf-8").splitlines() if line]

    # הגנה: עמודים עם תוכן זהה (מאמרים שנמחקו והפנו לעמוד המדור) - עותק אחד בלבד,
    # עם הכתובת הקצרה ביותר
    seen, unique_pages = set(), []
    for page in sorted(pages, key=lambda p: len(p["url"])):
        key = hashlib.md5(page["content_md"].encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique_pages.append(page)
    print(f"📄 עמודים: {len(pages)}  (ייחודיים: {len(unique_pages)})")

    all_chunks = []
    for page in unique_pages:
        sections = split_by_headings(clean_page(page["content_md"]))
        for index, (headings, body) in enumerate(merge_and_split(sections)):
            if words(body) >= 15:  # פחות מ-15 מילים = כנראה שארית (כפתור, כותרת בודדת)
                all_chunks.append(make_chunk(page, headings, body, index))

    # פסקה זהה שמופיעה בכמה עמודים (למשל אותה שאלה נפוצה) - נשמרת פעם אחת
    seen, unique_chunks = set(), []
    for chunk in all_chunks:
        key = hashlib.md5(chunk["body"].encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique_chunks.append(chunk)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for chunk in unique_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    sizes = [c["word_count"] for c in unique_chunks]
    print(f"✂️  פסקאות: {len(unique_chunks)}  (הוסרו {len(all_chunks) - len(unique_chunks)} כפולות)")
    print(f"📏 מילים בפסקה: חציון {statistics.median(sizes):.0f}, מינימום {min(sizes)}, מקסימום {max(sizes)}")
    print(f"   קטנות מ-{MIN_WORDS}: {sum(s < MIN_WORDS for s in sizes)}  |  גדולות מ-{MAX_WORDS}: {sum(s > MAX_WORDS for s in sizes)}")
    print(f"💾 נשמר ל: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

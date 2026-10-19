"""
שלב 1: סריקת אתר הפניקס, ורענון המידע
======================================
מה הקובץ הזה עושה, בקצרה:
  1. קורא את ה-sitemap (רשימת כל העמודים באתר) ומסנן רק עמודים רלוונטיים
  2. לכל עמוד: אם כבר יש לנו אותו - שואל את האתר "השתנית?" (ETag).
     האתר עונה "לא השתנה" בלי לשלוח כלום, או שולח את הגרסה החדשה.
  3. עמוד חדש או שהשתנה - מנקה אותו (רק התוכן המרכזי, בלי תפריטים) וממיר ל-Markdown
  4. בודק איכות: טקסט פגום (xxx), עמודים כמעט ריקים, כפילויות,
     וירידה חדה במספר העמודים (= תקלה, ואז לא שומרים כלום)
  5. שומר ל-data/pages.jsonl, ואת השינויים מהריצה הקודמת ל-data/changes.json

איך מריצים:
  בדיקה על 10 עמודים בלבד:   python ingest/crawl.py --test 10
  סריקה / רענון:             python ingest/crawl.py
  להוריד הכול מחדש:          python ingest/crawl.py --refresh-all
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import requests

# אישורי אבטחה (SSL): בודקים את האתר מול מאגר האישורים של Windows עצמו,
# ולא מול הרשימה הפנימית של פייתון. זה פותר שגיאת CERTIFICATE_VERIFY_FAILED
# ברשת שעוברת דרך סינון/אנטי-וירוס (שמוסיפים אישור משלהם ל-Windows).
# האבטחה לא נחלשת - האישור עדיין נבדק, רק מול המאגר של מערכת ההפעלה.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
from bs4 import BeautifulSoup
from markdownify import markdownify

# ------------------------------------------------------------
# הגדרות - כאן משנים את ההתנהגות של הסורק
# ------------------------------------------------------------

SITEMAP_URL = "https://www.fnx.co.il/sitemap.xml"

# אילו מדורים באתר אנחנו רוצות (לפי תחילת הכתובת)
INCLUDE_PREFIXES = [
    "/claims-customer-service/",   # תביעות - הכי חשוב!
    "/customer-service/",          # שירות לקוחות
    "/apartment-insurance/",       # ביטוח דירה
    "/car-insurance/",             # ביטוח רכב
    "/health-insurance/",          # ביטוח בריאות
    "/travel-insurance/",          # ביטוח נסיעות
    "/life-insurance/",            # ביטוח חיים
    "/mortgage-insurance/",        # ביטוח משכנתא
    "/disability-and-incapacity-to-work/",  # אובדן כושר עבודה
    "/pets-insurance/",            # חיות מחמד
    "/business-insurance/",        # ביטוח לעסקים
    "/pension-savings/",           # פנסיה
    "/gemel/",                     # קופת גמל
    "/ishtalmutfund/",             # קרן השתלמות
    "/savings/",                   # חיסכון
    "/loans/",                     # הלוואות
]

# אילו כתובות לדלג עליהן (חסומות ב-robots.txt או לא רלוונטיות)
EXCLUDE_PATTERNS = [
    "/en/", "/career/", "/investor-relations/", "/more-information/",
    "/class-actions/",   # הודעות משפטיות על תביעות ייצוגיות - לא מידע שלקוח שואל עליו
    "/accessibility/",   # הצהרת נגישות של האתר עצמו
    "?page=", "?domain=", "?tag=", "?staff=",
]

# כמה שניות לחכות בין בקשות (קצב מנומס - לא להעמיס על האתר)
# התחלנו ב-1 שנייה, אבל בבדיקה האתר התחיל לנתק אותנו (ConnectionError) - אז האטנו ל-2
DELAY_SECONDS = 2.0

# "תעודת הזהות" שלנו - אומרים בכנות מי אנחנו
USER_AGENT = "FnxHackathonBot/1.0 (student hackathon project, polite crawler)"

# עמוד עם פחות מילים מזה הוא עמוד "דל" (למשל רק קישורים ל-PDF) - מדלגים עליו
MIN_WORDS = 50

# תיקיות הפלט
DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw_html"
OUTPUT_FILE = DATA_DIR / "pages.jsonl"
FAILED_FILE = DATA_DIR / "failed.txt"


# ------------------------------------------------------------
# חלק 1: קריאת ה-sitemap וסינון
# ------------------------------------------------------------

def read_sitemap(session):
    """מוריד את ה-sitemap ומחזיר רשימה של (כתובת, תאריך עדכון)."""
    print(f"📥 קוראת את ה-sitemap: {SITEMAP_URL}")
    response = session.get(SITEMAP_URL, timeout=30)
    response.raise_for_status()

    # ה-sitemap כתוב ב-XML. כל עמוד נמצא בתוך תגית <url>
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ElementTree.fromstring(response.content)

    pages = []
    for url_tag in root.findall("sm:url", namespace):
        loc = url_tag.findtext("sm:loc", default="", namespaces=namespace).strip()
        lastmod = url_tag.findtext("sm:lastmod", default="", namespaces=namespace).strip()
        pages.append((loc, lastmod[:10]))  # [:10] = רק התאריך, בלי השעה

    print(f"   נמצאו {len(pages)} עמודים ב-sitemap")
    return pages


def is_relevant(url):
    """האם הכתובת שייכת למדור שאנחנו רוצות, ולא לרשימת הדילוג?"""
    path = url.replace("https://www.fnx.co.il", "")
    if any(pattern in url for pattern in EXCLUDE_PATTERNS):
        return False
    return any(path.startswith(prefix) for prefix in INCLUDE_PREFIXES)


def section_of(url):
    """מחזיר את שם המדור מתוך הכתובת. למשל: apartment-insurance"""
    path = url.replace("https://www.fnx.co.il/", "")
    return path.split("/")[0] if path else "home"


def pick_test_sample(pages, n):
    """
    לבדיקה: בוחרת עמודים ממדורים שונים, וגם מעומקים שונים
    (עמודי פתיחה של מדור, מאמרים, עמודי תביעות) - כדי לראות מגוון סוגי עמודים.
    """
    import random
    random.seed(42)  # אותו מדגם בכל הרצה, כדי שנוכל להשוות לפני ואחרי תיקון

    by_section = {}
    for url, lastmod in pages:
        by_section.setdefault(section_of(url), []).append((url, lastmod))
    for section in by_section:
        first, rest = by_section[section][:1], by_section[section][1:]
        random.shuffle(rest)
        # עמוד "עמוק" אקראי, ואחריו עמוד הפתיחה של המדור
        by_section[section] = rest[:1] + first + rest[1:]

    # מדורי התביעות והשירות ראשונים - הם הכי חשובים לבוט
    priority = ["claims-customer-service", "customer-service"]
    by_section = dict(sorted(by_section.items(), key=lambda kv: kv[0] not in priority))

    sample = []
    # סבב: עמוד אחד מכל מדור, ואז עוד סבב, עד שמגיעים ל-n
    while len(sample) < n and any(by_section.values()):
        for section in list(by_section):
            if by_section[section] and len(sample) < n:
                sample.append(by_section[section].pop(0))
    return sample


# ------------------------------------------------------------
# חלק 2: הורדת עמוד (עם ניסיונות חוזרים)
# ------------------------------------------------------------

# זמני המתנה בין ניסיונות חוזרים. כל פעם מחכים יותר ("exponential backoff"):
# אם האתר מנתק אותנו כי הוא עמוס או חושד בנו, נותנים לו זמן להירגע.
BACKOFF_SECONDS = [5, 15, 30, 60]

# סימן מיוחד: העמוד נמחק מהאתר (404). זה לא "כישלון" - פשוט אין מה להוריד.
# בבדיקה מצאנו 35 עמודי תביעות עם כתובת בעברית שמחזירים 404,
# והתוכן שלהם קיים באתר תחת כתובת באנגלית (למשל claims-in-case-of-death).
NOT_FOUND = "NOT_FOUND"


def download(session, url, etag=None):
    """
    מוריד עמוד. מחזיר (סטטוס, html, etag).
    אם שולחים etag - זו שאלה "השתנית מאז?". אם לא, האתר עונה 304 ולא שולח כלום.
    אם נכשל - מנסה שוב, ומחכה יותר בכל פעם: 5, 15, 30, 60 שניות.
    """
    headers = {"If-None-Match": etag} if etag else {}
    for attempt, wait in enumerate(BACKOFF_SECONDS, start=1):
        try:
            response = session.get(url, timeout=30, headers=headers)
            if response.status_code == 200:
                return "ok", response.text, response.headers.get("ETag")
            if response.status_code == 304:  # "לא השתנה" - 0 בתים
                return "unchanged", None, etag
            if response.status_code == 404:  # העמוד לא קיים - אין טעם לנסות שוב
                return "not_found", None, None
            print(f"   ⚠️  קוד {response.status_code} (ניסיון {attempt}) - מחכה {wait} שניות")
        except requests.RequestException as error:
            print(f"   ⚠️  {type(error).__name__} (ניסיון {attempt}) - מחכה {wait} שניות")
        time.sleep(wait)
    return "failed", None, None


# "יומן הסריקה": לכל כתובת - טביעת האצבע (ETag) שלה בהורדה האחרונה, ומה יצא ממנה.
# הקובץ נשמר ב-GitHub, ולכן הרענון עובד גם בענן, בלי ה-HTML הגולמי שנשאר רק במחשב.
STATE_FILE = DATA_DIR / "crawl_state.json"


def load_state():
    if not STATE_FILE.exists():
        return {}
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    # גרסה ישנה של היומן שמרה רק תאריך (מחרוזת). בלי ETag - ההורדה הבאה תהיה מלאה.
    return {url: value for url, value in state.items() if isinstance(value, dict)}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# למה ETag ולא תאריך העדכון ב-sitemap? בדקנו מול האתר:
#   - עמוד מסלול פנסיה: הנתונים עודכנו ל-31.08, ובאתר התאריך נשאר 16.08
#   - עמוד "טופס 161": נכתב מחדש, והתאריך נשאר 14.11.2024
# ה-ETag של האתר מחושב מתוכן העמוד עצמו (גודל + SHA-1, אימתנו בחישוב),
# כך שכל שינוי בעמוד משנה אותו - וזה בדיוק מה שצריך.
def get_page(session, url, state, previous_records, refresh_all=False):
    """
    מחזירה (סוג, תוכן):
      ("downloaded", html)   - עמוד חדש או שהשתנה, ירד עכשיו
      ("unchanged", record)  - האתר אמר "לא השתנה" - לוקחים את הגרסה הקודמת
      ("unchanged_thin", None) - "לא השתנה", והוא היה עמוד דל - ממשיכים לדלג
      ("kept", record)       - ההורדה נכשלה, שומרים את הגרסה הקודמת עד הריצה הבאה
      ("not_found", None)    - העמוד נמחק מהאתר (404)
      ("failed", None)       - ההורדה נכשלה ואין גרסה קודמת
    """
    known = state.get(url, {})
    previous = previous_records.get(url)
    etag = None if refresh_all else known.get("etag")

    # שואלים "השתנית?" רק אם יש לנו לאן לחזור כשהתשובה היא "לא"
    if etag and not (previous or known.get("status") == "thin"):
        etag = None

    status, html, new_etag = download(session, url, etag)
    if status == "unchanged":
        return ("unchanged", previous) if previous else ("unchanged_thin", None)
    if status == "ok":
        state[url] = {"etag": new_etag}
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / raw_filename(url)).write_text(html, encoding="utf-8")  # עותק מקומי לבדיקות
        return "downloaded", html
    if status == "not_found":
        state.pop(url, None)
        return "not_found", None
    if previous:
        print("   ⚠️  ההורדה נכשלה - משאירים את הגרסה הקודמת, וננסה שוב בריצה הבאה")
        return "kept", previous
    return "failed", None


def content_hash(record):
    return hashlib.md5(record["content_md"].encode("utf-8")).hexdigest()


def load_previous_pages():
    """הגרסה הקודמת של pages.jsonl: כתובת -> העמוד. משמשת כשהאתר עונה "לא השתנה"."""
    if not OUTPUT_FILE.exists():
        return {}
    previous = {}
    for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
        if line:
            record = json.loads(line)
            previous[record["url"]] = record
    return previous


def compare_with_previous(previous, records):
    """
    משווה את הסריקה הנוכחית לקודמת, לפי התוכן עצמו (לא לפי תאריכים):
      new     - עמוד שלא היה קודם (האתר הוסיף מידע)
      updated - עמוד שהתוכן שלו השתנה
      removed - עמוד שהיה ועכשיו איננו (נמחק מהאתר / יצא מה-sitemap)
    שלב האינדקס ישתמש ברשימות האלה כדי לעדכן רק את מה שצריך.
    """
    current = {r["url"]: content_hash(r) for r in records}
    previous = {url: content_hash(r) for url, r in previous.items()}
    return {
        "new": sorted(u for u in current if u not in previous),
        "updated": sorted(u for u in current if u in previous and previous[u] != current[u]),
        "removed": sorted(u for u in previous if u not in current),
    }


def raw_filename(url):
    """שם קובץ קצר וייחודי לכל כתובת (כי כתובות ארוכות מדי לשם קובץ)."""
    return hashlib.md5(url.encode()).hexdigest()[:16] + ".html"


# ------------------------------------------------------------
# חלק 3: שליפת התוכן הנקי
# ------------------------------------------------------------

def find_breadcrumb(soup):
    """
    מוצאת את "פירורי הלחם" (דף הבית > ביטוח דירה > ...).
    מחפשת רשימה שהקישור הראשון בה הוא "דף הבית".
    """
    for lst in soup.find_all(["ol", "ul"]):
        links = lst.find_all("a")
        if links and links[0].get_text(strip=True) == "דף הבית":
            items = [li.get_text(" ", strip=True) for li in lst.find_all("li")]
            items = [item for item in items if item and item != "דף הבית"]
            # הפריט האחרון הוא בדרך כלל שם העמוד עצמו - לא צריך אותו
            return " > ".join(items[:-1]) if len(items) > 1 else " > ".join(items)
    return ""


def remove_junk(main):
    """מוחקת מתוך התוכן המרכזי חלקים שהם לא תוכן אמיתי."""
    # תגיות שאף פעם לא תוכן
    # שימו לב: לא מוחקים <header> - בתוך התוכן הוא עוטף כותרות חשובות כמו "שאלות נפוצות"
    for tag in main.select("script, style, noscript, svg, img, iframe, form, button, footer, nav"):
        tag.decompose()

    # רשימת פירורי הלחם - כבר שמרנו אותה בנפרד
    for lst in main.find_all(["ol", "ul"]):
        links = lst.find_all("a")
        if links and links[0].get_text(strip=True) == "דף הבית":
            lst.decompose()

    # כפתורי שיתוף (פייסבוק/וואטסאפ)
    # שימו לב: כשמוחקים <li> שלם, קישורים אחרים שהיו בתוכו כבר "מתים".
    # לכן בודקים link.decomposed ומדלגים עליהם - אחרת התוכנה קורסת (זה הבאג שתיקנו!)
    for link in main.find_all("a", href=True):
        if link.decomposed:
            continue
        href = link.get("href", "")
        if "facebook.com/sharer" in href or "whatsapp.com/send" in href:
            parent = link.find_parent("li") or link
            parent.decompose()

    # אזורים שלמים שאינם תוכן העמוד. את שמות ה-class מצאנו בבדיקת ה-HTML האמיתי:
    #   news-section / promoted-articles  = "אולי יעניין אותך" (תקצירים של מאמרים אחרים)
    #   contacts-section                  = "כל הדרכים לדבר איתנו" (חוזר בכל עמוד)
    #   service-wide                      = "כבר יש לך ביטוח?" (כפתורי פעולות מהירות)
    #   aside                             = בעמודי מאמרים: עמודה צדדית עם "מאמרים נוספים"
    for block in main.select(".news-section, .promoted-articles, .contacts-section, .service-wide, aside"):
        block.decompose()

    # כפתורים ("לרכישת ביטוח", "עוד", "סגור", "לכל הכתבות") - טקסט של ממשק, לא מידע
    #   rte-btn-primary = כפתור שמופיע בתוך טקסט של מאמר ("לקבלת הצעה לביטוח מקיף")
    for btn in main.select(".btn, .btn-hold, .button-with-popup, .insurance-card-opener, .rte-btn-primary"):
        btn.decompose()

    # גיבוי לעמודים במבנה אחר: מוחקים לפי הכותרת "אולי יעניין אותך"
    for heading in main.find_all(["h2", "h3"]):
        if "אולי יעניין אותך" in heading.get_text():
            container = heading.find_parent(class_="section-item") or heading.find_parent("section") or heading.parent
            container.decompose()
            break


def clean_markdown(text):
    """ניקוי אחרון: שורות ריקות כפולות, רווחים מיותרים."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()


def extract(html, url, lastmod):
    """מקבלת HTML של עמוד ומחזירה כרטיסייה מסודרת עם התוכן הנקי."""
    soup = BeautifulSoup(html, "html.parser")

    # כותרת: קודם h1, ואם אין - תגית title
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    else:
        title = soup.title.get_text(strip=True).replace("| הפניקס", "").strip() if soup.title else ""

    breadcrumb = find_breadcrumb(soup)

    # התוכן המרכזי: האזור שמסומן main. אם לא נמצא - כל העמוד (ונקבל אזהרה בבדיקה)
    main = soup.select_one("#main") or soup.find("main") or soup.body
    remove_junk(main)

    # המרה ל-Markdown תוך שמירה על הכותרות כ-## (חשוב לשלב החיתוך!)
    content = clean_markdown(markdownify(str(main), heading_style="ATX", strip=["a"]))

    return {
        "url": url,
        "title": title,
        "breadcrumb": breadcrumb,
        "section": section_of(url),
        "lastmod": lastmod,
        "crawled_at": date.today().isoformat(),
        "word_count": len(content.split()),
        "source": "requests",
        "content_md": content,
    }


def remove_duplicates(records):
    """מקבצת עמודים עם תוכן זהה, ומשאירה מכל קבוצה רק את בעל הכתובת הקצרה ביותר."""
    groups = {}
    for record in records:
        key = hashlib.md5(record["content_md"].encode("utf-8")).hexdigest()
        groups.setdefault(key, []).append(record)

    kept, removed = [], []
    for group in groups.values():
        group.sort(key=lambda r: len(r["url"]))
        kept.append(group[0])
        removed.extend(f"{r['url']}  (זהה ל: {group[0]['url']})" for r in group[1:])
    return kept, removed


# ------------------------------------------------------------
# חלק 4: בדיקת איכות
# ------------------------------------------------------------

# מילים שהוחלפו ב-"xxx". כך נראה טקסט שעבר דרך רשת מסוננת (מצאנו 3 עמודים כאלה).
# עמוד כזה לא נכנס למידע - הבוט לא צריך לצטט טקסט פגום.
MASKED = re.compile(r"\bx{3,}\b")

# אם פתאום יש הרבה פחות עמודים מבריצה הקודמת - כנראה תקלה (חסימה, שינוי עיצוב),
# לא שינוי אמיתי באתר. במקרה כזה לא שומרים, והמידע הקודם נשאר.
MIN_PAGES_RATIO = 0.9

# מילים שמופיעות רק בתפריט/בפוטר. אם הן בתוכן - הניקוי לא עבד
NAV_MARKERS = ["פורטל סוכנים", "פורטל מעסיקים", "כל הזכויות שמורות", "close mobile menu"]


def quality_report(records, failed):
    print("\n" + "=" * 60)
    print("📊 דוח איכות")
    print("=" * 60)
    print(f"✅ עמודים שנשמרו:  {len(records)}")
    print(f"❌ עמודים שנכשלו:  {len(failed)}")

    if records:
        words = [r["word_count"] for r in records]
        print(f"📝 מילים בעמוד:    ממוצע {sum(words) // len(words)}, מינימום {min(words)}, מקסימום {max(words)}")
        no_crumb = sum(1 for r in records if not r["breadcrumb"])
        print(f"🍞 בלי פירורי לחם: {no_crumb}")

    suspicious = []
    for r in records:
        problems = []
        if r["word_count"] < MIN_WORDS:
            problems.append("מעט מדי מילים")
        if any(marker in r["content_md"] for marker in NAV_MARKERS):
            problems.append("נראה שיש תפריט בתוכן")
        if not r["title"]:
            problems.append("אין כותרת")
        if problems:
            suspicious.append((r["url"], problems))

    if suspicious:
        print(f"\n⚠️  {len(suspicious)} עמודים חשודים - כדאי לבדוק אותם:")
        for url, problems in suspicious[:15]:
            print(f"   - {url}\n     {', '.join(problems)}")
    else:
        print("\n🎉 לא נמצאו עמודים חשודים")


# ------------------------------------------------------------
# התוכנית הראשית
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="סורק אתר הפניקס")
    parser.add_argument("--refresh-all", action="store_true",
                        help="להוריד מחדש את כל העמודים, בלי לשאול 'השתנית?'")
    parser.add_argument("--test", type=int, default=0,
                        help="מספר עמודים לבדיקה (למשל 10). בלי זה - סריקה מלאה")
    args = parser.parse_args()

    # Session = שומר עוגיות בין בקשות (פותר את בעיית ההפניות החוזרות)
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "he-IL,he;q=0.9",
    })

    all_pages = read_sitemap(session)
    pages = [(url, lastmod) for url, lastmod in all_pages if is_relevant(url)]
    print(f"   אחרי סינון: {len(pages)} עמודים רלוונטיים")

    if args.test:
        pages = pick_test_sample(pages, args.test)
        print(f"\n🧪 מצב בדיקה: {len(pages)} עמודים ממדורים שונים")

    estimated_minutes = len(pages) * (DELAY_SECONDS + 0.5) / 60
    print(f"⏱️  זמן משוער: כ-{estimated_minutes:.0f} דקות\n")

    records, failed, thin, not_found, masked = [], [], [], [], []
    counts = {"downloaded": 0, "unchanged": 0, "kept": 0}
    state = {} if args.test else load_state()
    previous = {} if args.test else load_previous_pages()

    for i, (url, lastmod) in enumerate(pages, start=1):
        print(f"[{i}/{len(pages)}] {url}")
        kind, content = get_page(session, url, state, previous, args.refresh_all)
        time.sleep(DELAY_SECONDS)  # קצב מנומס

        if kind == "not_found":
            not_found.append(url)
            print("   🗑️  העמוד נמחק מהאתר (404) - מדלגים")
            continue
        if kind == "unchanged_thin":
            thin.append(url)
            print("   ⏭️  עמוד דל, לא השתנה - מדלגים")
            continue
        if kind == "failed":
            failed.append(url)
            print("   ✗ נכשל")
            continue
        if kind in ("unchanged", "kept"):
            counts[kind] += 1
            records.append(content)
            print(f"   {'💤' if kind == 'unchanged' else '📂'} לא השתנה | {content['title'][:50]}")
            continue

        # kind == "downloaded": עמוד חדש או שהשתנה - מנקים אותו
        counts["downloaded"] += 1
        try:
            # רשת ביטחון: עמוד אחד מוזר לא יעצור סריקה של 1,000 עמודים
            record = extract(content, url, lastmod)
        except Exception as error:
            print(f"   ⚠️  שגיאה בניקוי: {type(error).__name__}: {error}")
            failed.append(url)
            continue

        if MASKED.search(record["content_md"]):
            print("   🚫 בטקסט יש מילים שהוחלפו ב-xxx (רשת מסוננת?) - לא נכנס למידע")
            masked.append(url)
            state.pop(url, None)  # בפעם הבאה יורד מחדש במלואו
            if url in previous:
                records.append(previous[url])
            continue

        if record["word_count"] < MIN_WORDS:
            # עמוד דל באמת (למשל רק קישורים ל-PDF) - מדלגים
            print(f"   ⏭️  עמוד דל ({record['word_count']} מילים) - מדלגים")
            thin.append(url)
            state[url]["status"] = "thin"
            continue

        state[url]["status"] = "ok"
        records.append(record)
        print(f"   ✓ {record['title'][:50]} | {record['word_count']} מילים | {record['breadcrumb']}")

    # הסרת כפילויות: מאמרים שנמחקו מהאתר מחזירים את עמוד המדור במקומם,
    # ואז אותו תוכן נשמר כמה פעמים תחת כתובות שונות. משאירים עותק אחד -
    # זה עם הכתובת הקצרה ביותר (בדרך כלל העמוד "האמיתי").
    records, duplicates = remove_duplicates(records)

    # שומר איכות: ירידה חדה במספר העמודים = כנראה תקלה. לא שומרים כלום.
    if previous and len(records) < MIN_PAGES_RATIO * len(previous):
        print(f"\n🛑 נשמרו רק {len(records)} עמודים, לעומת {len(previous)} בריצה הקודמת.")
        print("   זה נראה כמו תקלה (חסימה / שינוי עיצוב באתר), לא כמו שינוי אמיתי.")
        print("   לא נשמר כלום - המידע הקודם נשאר כמו שהוא.")
        sys.exit(1)

    output = DATA_DIR / ("pages_test.jsonl" if args.test else OUTPUT_FILE.name)
    with open(output, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    FAILED_FILE.write_text("\n".join(failed), encoding="utf-8")
    for name, items in [("thin", thin), ("not_found", not_found), ("duplicates", duplicates), ("masked", masked)]:
        (DATA_DIR / f"{name}.txt").write_text("\n".join(items), encoding="utf-8")
    changes = compare_with_previous(previous, records) if previous else None
    if changes:
        (DATA_DIR / "changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.test:
        save_state(state)

    quality_report(records, failed)
    print(f"📥 ירדו: {counts['downloaded']}  |  💤 לא השתנו: {counts['unchanged']}  |  📂 נשמרה גרסה קודמת: {counts['kept']}")
    print(f"⏭️  עמודים דלים: {len(thin)}  |  🗑️  נמחקו מהאתר: {len(not_found)}  |  🧹 כפולים: {len(duplicates)}  |  🚫 טקסט פגום: {len(masked)}")
    if changes:
        print(f"\n📰 שינויים מאז הסריקה הקודמת (data/changes.json):")
        print(f"   ➕ עמודים חדשים: {len(changes['new'])}")
        print(f"   ✏️  עמודים שהתוכן שלהם השתנה: {len(changes['updated'])}")
        print(f"   ➖ עמודים שהוסרו: {len(changes['removed'])}")
    print(f"\n💾 נשמר ל: {output}")


if __name__ == "__main__":
    main()

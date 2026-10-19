"""
שלב 1: סריקת אתר הפניקס
=========================
מה הקובץ הזה עושה, בקצרה:
  1. קורא את ה-sitemap (רשימת כל העמודים באתר)
  2. מסנן רק את העמודים שרלוונטיים ללקוח
  3. מוריד כל עמוד בקצב מנומס (בקשה אחת בשנייה)
  4. שומר את ה-HTML הגולמי לדיסק (כדי לא לסרוק שוב אם נשפר את הניקוי)
  5. שולף רק את התוכן המרכזי (בלי תפריטים ופוטר) וממיר ל-Markdown
  6. שומר הכל לקובץ data/pages.jsonl

איך מריצים:
  בדיקה על 10 עמודים בלבד (מומלץ להתחיל ככה!):
      python ingest/crawl.py --test 10

  סריקה מלאה:
      python ingest/crawl.py
"""

import argparse
import hashlib
import json
import re
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


def download(session, url):
    """מוריד עמוד. אם נכשל - מנסה שוב, ומחכה יותר בכל פעם: 5, 15, 30, 60 שניות."""
    for attempt, wait in enumerate(BACKOFF_SECONDS, start=1):
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 200:
                return response.text
            if response.status_code == 404:  # העמוד לא קיים - אין טעם לנסות שוב
                return NOT_FOUND
            print(f"   ⚠️  קוד {response.status_code} (ניסיון {attempt}) - מחכה {wait} שניות")
        except requests.RequestException as error:
            print(f"   ⚠️  {type(error).__name__} (ניסיון {attempt}) - מחכה {wait} שניות")
        time.sleep(wait)
    return None


# "יומן הסריקה": לכל כתובת - מה היה תאריך העדכון שלה (lastmod) כשהורדנו אותה
STATE_FILE = DATA_DIR / "crawl_state.json"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# בדקנו מול האתר: בעמוד מסלול פנסיה כתוב "הנתונים מעודכנים לתאריך 31.08.2026",
# אבל ה-lastmod שלו ב-sitemap הוא 16.08.2026. כלומר הנתונים (תשואות, דמי ניהול)
# מתעדכנים בלי ש-lastmod משתנה! לכן lastmod לבדו לא מספיק,
# ועמוד ישן מ-MAX_CACHE_AGE_DAYS יורד מחדש בכל מקרה.
MAX_CACHE_AGE_DAYS = 7


def cache_age_days(path):
    return (time.time() - path.stat().st_mtime) / 86400


def get_html(session, url, lastmod, state, refresh_all=False):
    """
    מחזירה את ה-HTML של עמוד, ואומרת מאיפה הוא הגיע.

    קוראים מהמטמון (בלי לפנות לאתר) רק אם שלושה תנאים מתקיימים:
      1. העמוד כבר ירד בעבר
      2. ה-lastmod שלו ב-sitemap לא השתנה מאז
      3. ההורדה האחרונה שלו לא ישנה מ-MAX_CACHE_AGE_DAYS ימים
    אחרת - מורידים מחדש.
    """
    cached = RAW_DIR / raw_filename(url)
    known = state.get(url)  # ה-lastmod שהיה כשהורדנו. None = לא רשום (הורד לפני שהיה יומן)

    fresh = (
        cached.exists()
        and (known is None or known == lastmod)
        and cache_age_days(cached) < MAX_CACHE_AGE_DAYS
        and not refresh_all
    )
    if fresh:
        state[url] = lastmod
        return cached.read_text(encoding="utf-8"), "cache"

    had_old_copy = cached.exists()
    html = download(session, url)
    if html == NOT_FOUND:
        return None, "not_found"
    if html:
        cached.write_text(html, encoding="utf-8")
        state[url] = lastmod
        return html, ("refreshed" if had_old_copy else "web")
    if had_old_copy:
        # ההורדה של הגרסה החדשה נכשלה - עדיף גרסה ישנה מכלום. ננסה שוב בהרצה הבאה.
        print("   ⚠️  לא הצלחנו להוריד את הגרסה החדשה - משתמשים בגרסה הישנה")
        return cached.read_text(encoding="utf-8"), "cache"
    return None, "web"


def content_hash(record):
    return hashlib.md5(record["content_md"].encode("utf-8")).hexdigest()


def load_previous_pages():
    """הגרסה הקודמת של pages.jsonl: כתובת -> טביעת אצבע של התוכן. ככה יודעים מה השתנה."""
    if not OUTPUT_FILE.exists():
        return {}
    previous = {}
    for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
        if line:
            record = json.loads(line)
            previous[record["url"]] = content_hash(record)
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
                        help="להוריד מחדש את כל העמודים, בלי מטמון")
    parser.add_argument("--test", type=int, default=0,
                        help="מספר עמודים לבדיקה (למשל 10). בלי זה - סריקה מלאה")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

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

    estimated_minutes = len(pages) * (DELAY_SECONDS + 1) / 60
    print(f"⏱️  זמן משוער: כ-{estimated_minutes:.0f} דקות\n")

    records, failed, thin, not_found = [], [], [], []
    state = load_state()
    previous = {} if args.test else load_previous_pages()

    for i, (url, lastmod) in enumerate(pages, start=1):
        print(f"[{i}/{len(pages)}] {url}")

        record = None
        html, origin = get_html(session, url, lastmod, state, args.refresh_all)
        if origin != "cache":
            time.sleep(DELAY_SECONDS)  # קצב מנומס - רק כשבאמת פנינו לאתר (לא כשקראנו מהמטמון)

        if html:
            # רשת ביטחון: אם עמוד אחד מוזר מפיל את הניקוי, רושמים אותו וממשיכים.
            # עמוד אחד שבור לא יעצור סריקה של 1,000 עמודים.
            try:
                record = extract(html, url, lastmod)
            except Exception as error:
                print(f"   ⚠️  שגיאה בניקוי: {type(error).__name__}: {error}")

        # עמוד שירד תקין אבל עם מעט טקסט = עמוד שבאמת כמעט ריק (למשל רק קישורים ל-PDF).
        # לא שולחים אותו ל-Jina, כי Jina יחזיר את כל התפריטים ויכניס רעש. רק מדלגים.
        if record and record["word_count"] < MIN_WORDS:
            print(f"   ⏭️  עמוד דל ({record['word_count']} מילים) - מדלגים")
            thin.append(url)
            continue

        # שימו לב: פעם היה כאן גיבוי דרך Jina Reader. בבדיקה ראינו שהוא מחזיר את העמוד
        # יחד עם כל התפריטים (אלפי מילים של רעש), אז הסרנו אותו.
        # עמוד שנכשל נרשם ב-failed.txt, ובהרצה הבאה ננסה רק אותו (השאר יגיעו מהמטמון).

        if origin == "not_found":
            not_found.append(url)
            print("   🗑️  העמוד נמחק מהאתר (404) - מדלגים")
            continue

        if record:
            records.append(record)
            tag = {"cache": "📂", "refreshed": "🔄", "web": "✓"}[origin]
            print(f"   {tag} {record['title'][:50]} | {record['word_count']} מילים | {record['breadcrumb']}")
        else:
            failed.append(url)
            print("   ✗ נכשל")

    # הסרת כפילויות: מאמרים שנמחקו מהאתר מחזירים את עמוד המדור במקומם,
    # ואז אותו תוכן נשמר כמה פעמים תחת כתובות שונות. בבוט זה היה גורם
    # לאותה פסקה להופיע 5 פעמים בתוצאות החיפוש. משאירים עותק אחד -
    # זה עם הכתובת הקצרה ביותר (בדרך כלל העמוד "האמיתי").
    records, duplicates = remove_duplicates(records)
    (DATA_DIR / "duplicates.txt").write_text("\n".join(duplicates), encoding="utf-8")
    print(f"\n🧹 עותקים כפולים שהוסרו: {len(duplicates)} (רשימה ב-data/duplicates.txt)")

    # שמירה: כל עמוד בשורה נפרדת
    output = DATA_DIR / ("pages_test.jsonl" if args.test else OUTPUT_FILE.name)
    with open(output, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    FAILED_FILE.write_text("\n".join(failed), encoding="utf-8")
    (DATA_DIR / "thin.txt").write_text("\n".join(thin), encoding="utf-8")
    changes = compare_with_previous(previous, records) if previous else None
    if changes:
        (DATA_DIR / "changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA_DIR / "not_found.txt").write_text("\n".join(not_found), encoding="utf-8")
    save_state(state)

    quality_report(records, failed)
    print(f"⏭️  עמודים דלים שדילגנו עליהם: {len(thin)} (רשימה ב-data/thin.txt)")
    print(f"🗑️  עמודים שנמחקו מהאתר (404): {len(not_found)} (רשימה ב-data/not_found.txt)")
    if changes:
        print(f"\n📰 שינויים מאז הסריקה הקודמת (data/changes.json):")
        print(f"   ➕ עמודים חדשים: {len(changes['new'])}")
        print(f"   ✏️  עמודים שהתוכן שלהם השתנה: {len(changes['updated'])}")
        print(f"   ➖ עמודים שהוסרו: {len(changes['removed'])}")
    print(f"\n💾 נשמר ל: {output}")
    if args.test:
        print("👀 עכשיו פתחו את הקובץ ובדקו 2-3 עמודים מול האתר בדפדפן!")


if __name__ == "__main__":
    main()

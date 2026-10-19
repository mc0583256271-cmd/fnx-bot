"""
כלי אבחון: למה עמודי התביעות עם כתובת בעברית נכשלים?
=========================================================
מריצים:   python ingest/diagnose.py

הוא בודק כתובת אחת בכמה דרכים, ומדפיס מה האתר עונה בכל צעד
(בלי לעקוב אוטומטית אחרי הפניות), כדי שנראה בדיוק איפה זה נתקע.
"""

from urllib.parse import quote, urlsplit, urlunsplit

import requests

URL = "https://www.fnx.co.il/claims-customer-service/claims-car-insurance/תביעה-במקרה-של-תאונה-ברכב-פרטי/"
USER_AGENT = "FnxHackathonBot/1.0 (student hackathon project, polite crawler)"


def encode(url, lower=False):
    """ממירה את החלק העברי בכתובת לקידוד אחוזים (%D7%AA...), באותיות גדולות או קטנות."""
    parts = urlsplit(url)
    path = quote(parts.path, safe="/-")
    if lower:
        path = path.lower()
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def trace(label, url):
    """עוקבת ידנית אחרי שרשרת ההפניות, עד 6 צעדים."""
    print(f"\n=== {label} ===")
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    for step in range(1, 7):
        try:
            r = session.get(url, timeout=30, allow_redirects=False)
        except requests.RequestException as error:
            print(f"  {step}. שגיאה: {type(error).__name__}: {error}")
            return
        print(f"  {step}. קוד {r.status_code}  ←  {url[:110]}")
        if r.status_code in (301, 302, 303, 307, 308):
            url = requests.compat.urljoin(url, r.headers.get("Location", ""))
            continue
        if r.status_code == 200:
            print(f"     ✓ הצליח. אורך העמוד: {len(r.text):,} תווים")
        return
    print("  ✗ יותר מדי הפניות - זו לולאה")


trace("א. הכתובת כמו שהיא ב-sitemap", URL)
trace("ב. קידוד אחוזים באותיות גדולות", encode(URL))
trace("ג. קידוד אחוזים באותיות קטנות", encode(URL, lower=True))
trace("ד. בלי הסלש בסוף", URL.rstrip("/"))

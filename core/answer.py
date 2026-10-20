"""
שלב 3: שכבת התשובה.

מה קורה בכל שאלה:
  1. שאלת המשך (יש היסטוריה) -> מודל השפה מנסח אותה כשאלה מלאה ("ותוך כמה זמן?" ->
     "תוך כמה זמן מקבלים תשובה על תביעת נזקי מים בביטוח דירה?"). שאלה ראשונה - בלי שלב זה.
  2. חיפוש 8 הקטעים הקרובים (core/retriever.py).
  3. אם גם הקטע הקרוב ביותר רחוק מאוד (דמיון < 0.60) -> "לא מצאתי" בלי לפנות למודל.
     (בבדיקה: כל השאלות שיש עליהן תשובה קיבלו 0.69 ומעלה. שאלות כמו "איך מכינים עוגת שוקולד" - 0.57.)
  4. מודל השפה (core/providers.py: Claude, ו-Gemini כגיבוי) מקבל את השאלה ואת הקטעים (עם כותרת ומדור),
     וכותב - מילה אחרי מילה (streaming) - שורת STATUS (answer / not_found / clarify), את התשובה,
     ושורת SOURCES עם מספרי הקטעים שבהם השתמש. ללקוח מוצג רק הטקסט.
  5. בדיקה בקוד: תשובה בלי מקור תקין = "לא מצאתי". הקישורים נבנים מהקטעים עצמם -
     המודל לא כותב כתובות, ולכן לא יכול להמציא קישור.

שימוש:
  from core.answer import answer
  result = answer("יש לי נזילה בבית, איך מגישים תביעה?")
  result = answer("ותוך כמה זמן מקבלים תשובה?", history=[{"role": "user", "text": "..."},
                                                         {"role": "assistant", "text": "..."}])
"""
import re
import time

from core.embeddings import Stop
from core.guardrails import small_talk_reply
from core.providers import Unavailable, default_provider
from core.retriever import Retriever

CONTACT_URL = "https://www.fnx.co.il/customer-service/contact-us/"
CONTACT_TITLE = "כל הדרכים ליצור איתנו קשר"
NOT_FOUND_TEXT = "לא מצאתי את המידע הזה באתר הפניקס. לבירור אפשר לפנות לשירות הלקוחות."
UNAVAILABLE_TEXT = "השירות לא זמין כרגע. אפשר לנסות שוב בעוד כמה דקות, או לפנות לשירות הלקוחות."
MIN_SCORE = 0.60          # מתחת לזה - לא שולחים למודל בכלל
HISTORY_TURNS = 6         # כמה הודעות אחרונות משמשות לניסוח שאלת המשך
KEYWORD_FALLBACK = False  # חיפוש מילים כשאין וקטורים - נכנס רק אחרי בדיקה ב-run_eval

ANSWER_SYSTEM = """אתה נציג שירות דיגיטלי של חברת הביטוח הפניקס. אתה עונה ללקוחות רק על סמך קטעים מאתר הפניקס שמצורפים להודעה.
עדיף לא לענות מאשר לענות תשובה לא נכונה.

כללים:
1. מקור יחיד: השתמש רק במידע שכתוב בקטעים. בלי ידע כללי, בלי השערות ובלי השלמות. מה שלא כתוב בקטעים - לא נכנס לתשובה.
2. התאמה: לכל קטע יש כותרת ומדור. השתמש רק בקטעים שעוסקים באותו מוצר שהלקוח שואל עליו (למשל ביטוח דירה ולא ביטוח עסק, פנסיה מקיפה ולא משלימה).
3. אין מידע: ענה רק אם הקטעים עונים ישירות על מה שנשאל. אם יש בקטעים רק מידע קרוב לנושא שלא עונה על השאלה עצמה - STATUS: not_found. במקרה של ספק - not_found.
4. העדף לענות כשהמידע קיים: אם התשובה שונה לפי אפשרויות שהלקוח לא ציין, אבל אפשר לתאר אותן בקצרה - ענה, ופרט כל אפשרות במשפט (למשל "אם יש לך שרברב בהסדר... ואם שרברב פרטי...").
   שאלת הבהרה (STATUS: clarify, שאלה קצרה אחת) - רק כשבקטעים יש כמה מסלולים, קרנות או מוצרים עם נתונים שונים (תשואה, דמי ניהול, תאריכים, סכומים) ואי אפשר לענות בלי לדעת על איזה מהם מדובר.
5. מידע אישי וייעוץ: אין לך גישה לפוליסה, לתביעה או לחשבון של הלקוח, ואתה לא נותן המלצה אישית. לעולם אל תשאל שאלת הבהרה על הפוליסה האישית.
   - שאלה על הפוליסה של הלקוח ("האם הפוליסה שלי מכסה...") - הסבר מה הכיסוי כולל לפי הקטעים, וסיים במשפט שאת הפוליסה האישית בודקים בשירות הלקוחות.
   - שאלה על פרט אישי (מספר הפוליסה, מצב התביעה, החשבון) - STATUS: not_found.
   - בקשה להמלצה ("מה הכי כדאי לי", "באיזה בנק/מסלול לבחור") - STATUS: not_found, אלא אם הקטעים עונים עליה במפורש.
6. סגנון: עברית ברורה ופשוטה. עד 3 משפטים קצרים, או עד 5 שלבים קצרים כשמדובר בתהליך. בלי פתיח ובלי ברכות.
7. אל תכתוב כתובות אתר בתוך התשובה.
8. הלקוח לא רואה את הקטעים: אל תכתוב "הקטעים", "לפי הקטעים" או "קטע מספר". כשמשהו לא מופיע - כתוב "באתר לא מופיע..." או "לפי המידע באתר...".

פורמט התשובה - בדיוק כך, שלושה חלקים:
STATUS: answer או not_found או clarify
הטקסט ללקוח (בשורה חדשה; ב-not_found אפשר להשאיר ריק)
SOURCES: מספרי הקטעים שהתשובה מבוססת עליהם, מופרדים בפסיק (למשל: SOURCES: 1, 3)"""

REWRITE_SYSTEM = """לפניך שיחה בין לקוח לבוט שירות של חברת הביטוח הפניקס, ושאלה חדשה של הלקוח.
נסח את השאלה החדשה כשאלה עצמאית ומלאה, שאפשר להבין בלי השיחה: השלם מהשיחה את הנושא (המוצר, סוג הביטוח, המסלול) רק אם השאלה החדשה ממשיכה אותו.
אם השאלה החדשה מובנת לבד, או עוברת לנושא אחר - החזר אותה כמו שהיא.
אל תענה על השאלה ואל תוסיף פרטים שלא נאמרו בשיחה.
החזר JSON בלבד: {"question": "..."}"""

_retriever = None
_keyword = None
_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        _provider = default_provider()
    return _provider


def _get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def search(question, mode="vectors"):
    """מחזיר (קטעים, איזה חיפוש שימש). mode="keywords" - לבדיקת הגיבוי בלבד."""
    global _keyword
    r = _get_retriever()
    if mode == "vectors":
        try:
            return r.search(question), "vectors"
        except Stop:
            if not KEYWORD_FALLBACK:
                raise
    if _keyword is None:
        from core.keyword_search import KeywordSearch
        _keyword = KeywordSearch(r.chunks)
    return _keyword.search(question), "keywords"


def rewrite_question(question, history, provider):
    turns = "\n".join(f"{'לקוח' if h['role'] == 'user' else 'בוט'}: {h['text'][:400]}"
                      for h in history[-HISTORY_TURNS:])
    data, _ = provider.generate(REWRITE_SYSTEM, f"השיחה:\n{turns}\n\nהשאלה החדשה: {question}")
    rewritten = str(data.get("question", "")).strip()
    return rewritten or question


def _passages_text(question, hits):
    parts = [f"שאלת הלקוח: {question}\n\nקטעים מאתר הפניקס:"]
    for n, h in enumerate(hits, 1):
        parts.append(f"[{n}] {h['text']}")  # text = כותרת הקשר (עמוד | מדור | נושא) + גוף הקטע
    return "\n\n".join(parts)


def _result(status, text, sources=(), **extra):
    return dict(status=status, answer=text, sources=list(sources), **extra)


STATUS_LINE = re.compile(r"^\s*\**\s*STATUS\s*:\s*\**\s*(answer|not_found|clarify)", re.IGNORECASE)
SOURCES_LINE = re.compile(r"^\s*\**\s*SOURCES\s*:(.*)$", re.IGNORECASE | re.MULTILINE)


def _parse(raw):
    """מפרק את תשובת המודל: (סטטוס, טקסט ללקוח, מספרי קטעים)."""
    lines = raw.strip().split("\n")
    status = None
    if lines and STATUS_LINE.match(lines[0]):
        status = STATUS_LINE.match(lines[0]).group(1).lower()
        lines = lines[1:]
    body = "\n".join(lines)
    numbers = []
    m = SOURCES_LINE.search(body)
    if m:
        numbers = [int(n) for n in re.findall(r"\d+", m.group(1))]
        body = body[:m.start()]
    return status, body.strip(), numbers


def _visible(raw):
    """החלק שאפשר כבר להציג תוך כדי כתיבה: בלי שורת STATUS ובלי שורת SOURCES (גם אם היא עוד באמצע)."""
    if "\n" not in raw:
        return ""  # עוד לא הסתיימה שורת הסטטוס
    first, rest = raw.split("\n", 1)
    if not STATUS_LINE.match(first):
        rest = raw  # המודל דילג על שורת הסטטוס
    m = SOURCES_LINE.search(rest)
    if m:
        rest = rest[:m.start()]
    else:
        last = rest.rsplit("\n", 1)[-1]
        token = re.sub(r"[\s*]", "", last).upper()
        if token and ("SOURCES:".startswith(token) or token.startswith("SOURCES")):
            rest = rest[:len(rest) - len(last)]  # תחילת שורת SOURCES שעוד נכתבת
    return rest.strip()


def answer_stream(question, history=None, provider=None, retrieval="vectors"):
    """אירועים לממשק: ("status", הודעת התקדמות), ("text", הטקסט עד עכשיו), ("final", התוצאה המלאה)."""
    history = history or []
    contact = [{"title": CONTACT_TITLE, "url": CONTACT_URL}]
    chat = small_talk_reply(question)  # "תודה", "שלום" - תשובה מיד, בלי חיפוש
    if chat:
        yield "final", _result("chat", chat, question=question, search_query=None, model=None,
                               retrieval=None, passages=[])
        return
    provider = provider or _get_provider()
    info = {"question": question, "search_query": question, "model": None}

    if history:
        yield "status", "מבין את ההקשר של השאלה..."
        try:
            info["search_query"] = rewrite_question(question, history, provider)
        except Unavailable:
            pass  # בלי ניסוח מחדש: מחפשים את השאלה כמו שהיא

    yield "status", "מחפש באתר הפניקס..."
    t0 = time.time()
    try:
        hits, used = search(info["search_query"], mode=retrieval)
    except Stop:
        yield "final", _result("unavailable", UNAVAILABLE_TEXT, contact, retrieval=None, passages=[], **info)
        return
    info.update(t_search=round(time.time() - t0, 1), retrieval=used,
                passages=[{"url": h["url"], "title": h["title"], "score": h["score"]} for h in hits])

    if used == "vectors" and hits[0]["score"] < MIN_SCORE:
        yield "final", _result("not_found", NOT_FOUND_TEXT, contact, reason="low_score", **info)
        return

    yield "status", "מנסח תשובה..."
    t0, raw, shown = time.time(), "", ""
    try:
        for chunk in provider.stream(ANSWER_SYSTEM, _passages_text(info["search_query"], hits)):
            raw += chunk
            status_now = STATUS_LINE.match(raw.split("\n", 1)[0]) if "\n" in raw else None
            if status_now and status_now.group(1).lower() == "not_found":
                continue  # לא מציגים - בסוף תוצג הודעת "לא מצאתי" הקבועה
            visible = _visible(raw)
            if visible and visible != shown:
                shown = visible
                yield "text", shown
    except Unavailable as e:
        yield "final", _result("unavailable", UNAVAILABLE_TEXT, contact, reason=str(e), **info)
        return
    info.update(t_llm=round(time.time() - t0, 1), model=getattr(provider, "model_used", None),
                t_first_text=getattr(provider, "first_chunk_seconds", None),
                llm_errors=list(getattr(provider, "last_errors", [])), raw=raw)

    status, text, numbers = _parse(raw)
    numbers = [n for i, n in enumerate(numbers) if 1 <= n <= len(hits) and n not in numbers[:i]]
    if status == "clarify" and text:
        yield "final", _result("clarify", text, **info)
        return
    if status in ("answer", None) and text and numbers:
        sources, seen = [], set()
        for n in numbers:
            h = hits[n - 1]
            if h["url"] not in seen:
                seen.add(h["url"])
                sources.append({"title": h["title"], "url": h["url"]})
        yield "final", _result("answer", text, sources, used_passages=numbers, **info)
        return
    # not_found, או תשובה בלי מקור תקין ("אין מקור - אין תשובה") - הטקסט שהוצג מוחלף
    reason = "model_not_found" if status == "not_found" else "no_valid_source"
    yield "final", _result("not_found", NOT_FOUND_TEXT, contact, reason=reason, **info)


def answer(question, history=None, provider=None, retrieval="vectors"):
    """אותו דבר בלי streaming: מחזיר רק את התוצאה הסופית (משמש את run_eval - אותו קוד בדיוק)."""
    final = None
    for kind, value in answer_stream(question, history, provider, retrieval):
        if kind == "final":
            final = value
    return final

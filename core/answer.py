"""
שלב 3: שכבת התשובה.

מה קורה בכל שאלה:
  1. שאלת המשך (יש היסטוריה) -> מודל השפה מנסח אותה כשאלה מלאה ("ותוך כמה זמן?" ->
     "תוך כמה זמן מקבלים תשובה על תביעת נזקי מים בביטוח דירה?"). שאלה ראשונה - בלי שלב זה.
  2. חיפוש 8 הקטעים הקרובים (core/retriever.py).
  3. אם גם הקטע הקרוב ביותר רחוק מאוד (דמיון < 0.60) -> "לא מצאתי" בלי לפנות למודל.
     (בבדיקה: כל השאלות שיש עליהן תשובה קיבלו 0.69 ומעלה. שאלות כמו "איך מכינים עוגת שוקולד" - 0.57.)
  4. מודל השפה (core/providers.py: רשימת מודלים, מעבר אוטומטי כשאחד עמוס) מקבל את השאלה ואת הקטעים (עם כותרת ומדור), ומחזיר אחד משלושה:
     answer (עם מספרי הקטעים שבהם השתמש) / not_found / clarify (שאלת הבהרה, למשל "באיזה מסלול?").
  5. בדיקה בקוד: תשובה בלי מקור תקין = "לא מצאתי". הקישורים נבנים מהקטעים עצמם -
     המודל לא כותב כתובות, ולכן לא יכול להמציא קישור.

שימוש:
  from core.answer import answer
  result = answer("יש לי נזילה בבית, איך מגישים תביעה?")
  result = answer("ותוך כמה זמן מקבלים תשובה?", history=[{"role": "user", "text": "..."},
                                                         {"role": "assistant", "text": "..."}])
"""
import time

from core.embeddings import Stop
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

כללים:
1. מקור יחיד: השתמש רק במידע שכתוב בקטעים. בלי ידע כללי, בלי השערות ובלי השלמות. מה שלא כתוב בקטעים - לא נכנס לתשובה.
2. התאמה: לכל קטע יש כותרת ומדור. השתמש רק בקטעים שעוסקים באותו מוצר שהלקוח שואל עליו (למשל ביטוח דירה ולא ביטוח עסק, פנסיה מקיפה ולא משלימה).
3. אין מידע: אם הקטעים לא עונים על השאלה - status="not_found". אל תענה חלקית מתוך קטעים שלא עונים עליה.
4. הבהרה: אם התשובה תלויה בפרט שהלקוח לא ציין (למשל איזה מסלול או איזו קרן, כשבקטעים יש כמה עם נתונים שונים) - status="clarify", ושאל שאלה קצרה אחת.
5. מידע אישי וייעוץ: אין לך גישה לפוליסה, לתביעה או לחשבון של הלקוח, ואתה לא נותן המלצה אישית. בשאלה כזו - הסבר מה כתוב בקטעים באופן כללי (אם יש), ואמור שאת הפרטים האישיים בודקים בשירות הלקוחות.
6. סגנון: עברית ברורה ופשוטה, עד 4 משפטים, או רשימת שלבים קצרה כשמדובר בתהליך. בלי פתיח ובלי ברכות.
7. מקורות: רשום בשדה sources את מספרי הקטעים שהתשובה מבוססת עליהם. אל תכתוב כתובות אתר בתוך התשובה.

החזר JSON בלבד:
{"status": "answer" או "not_found" או "clarify", "answer": "הטקסט ללקוח", "sources": [מספרי קטעים]}"""

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


def answer(question, history=None, provider=None, retrieval="vectors"):
    """מחזיר dict: status, answer, sources [{title,url}], ועוד פרטים לבדיקה (search_query, retrieval, passages)."""
    history = history or []
    provider = provider or _get_provider()
    contact = [{"title": CONTACT_TITLE, "url": CONTACT_URL}]
    info = {"question": question, "search_query": question, "model": None}

    if history:
        try:
            info["search_query"] = rewrite_question(question, history, provider)
        except Unavailable:
            pass  # בלי ניסוח מחדש: מחפשים את השאלה כמו שהיא

    t0 = time.time()
    try:
        hits, used = search(info["search_query"], mode=retrieval)
    except Stop:
        return _result("unavailable", UNAVAILABLE_TEXT, contact, retrieval=None, passages=[], **info)
    info.update(t_search=round(time.time() - t0, 1), retrieval=used, passages=[{"url": h["url"], "title": h["title"], "score": h["score"]} for h in hits])

    if used == "vectors" and hits[0]["score"] < MIN_SCORE:
        return _result("not_found", NOT_FOUND_TEXT, contact, reason="low_score", **info)

    t0 = time.time()
    try:
        data, info["model"] = provider.generate(ANSWER_SYSTEM, _passages_text(info["search_query"], hits))
        info["t_llm"] = round(time.time() - t0, 1)
    except Unavailable as e:
        return _result("unavailable", UNAVAILABLE_TEXT, contact, reason=str(e), **info)

    status = data.get("status")
    text = str(data.get("answer", "")).strip()
    numbers = []
    for n in data.get("sources") or []:
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= len(hits) and n not in numbers:
            numbers.append(n)

    if status == "clarify" and text:
        return _result("clarify", text, **info)
    if status == "answer" and text and numbers:
        sources, seen = [], set()
        for n in numbers:
            h = hits[n - 1]
            if h["url"] not in seen:
                seen.add(h["url"])
                sources.append({"title": h["title"], "url": h["url"]})
        return _result("answer", text, sources, used_passages=numbers, **info)
    # not_found, או תשובה בלי מקור תקין ("אין מקור - אין תשובה")
    reason = "model_not_found" if status == "not_found" else "no_valid_source"
    return _result("not_found", NOT_FOUND_TEXT, contact, reason=reason, **info)

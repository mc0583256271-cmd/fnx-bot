"""
שלב 2 (המשך): איזה חיפוש מוצא את הפסקה הנכונה לשאלה?

משווים שלוש שיטות על שאלות הבדיקה (eval/questions.json):
  1. מילים   - BM25 על שלישיות אותיות (טריגרמות). בלי AI, מהיר, חינם.
  2. משמעות  - הטמעות (embeddings) של Gemini. מבין ניסוחים שונים לאותו דבר.
  3. שילוב   - מאחדים את שתי הרשימות (RRF).

ובודקים גם את חצי הציון השני: בשאלות שאין עליהן תשובה באתר,
האם הציון של התוצאה הכי טובה נמוך מספיק כדי לדעת לסרב.

הרצה (מתיקיית הפרויקט):
  python eval/compare_search.py                 # הכל (צריך GEMINI_API_KEY בקובץ .env)
  python eval/compare_search.py --keyword-only  # רק חיפוש מילים, בלי Gemini
  python eval/compare_search.py --sample        # בדיקה זולה על כ-980 פסקאות (לפני שמטמיעים הכל)

ההטמעות נשמרות במטמון (data/emb_cache/). אם ההרצה נעצרה באמצע
(מגבלת קצב, רשת) - מריצים שוב והיא ממשיכה מאיפה שעצרה, בלי לשלם שוב.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import truststore  # אישורי SSL של Windows (סינון אינטרנט) - כמו ב-crawl.py
    truststore.inject_into_ssl()
except ImportError:
    pass
import numpy as np
import requests
from rank_bm25 import BM25Okapi

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_FILE = ROOT / "data" / "chunks.jsonl"
QUESTIONS_FILE = ROOT / "eval" / "questions.json"
RESULTS_FILE = ROOT / "eval" / "results_search.json"
ENV_FILE = ROOT / ".env"

MODEL = "gemini-embedding-2"
DIM = 3072            # הגודל המלא. 768 נבדק בנוסף ע"י קיצור הווקטור (בלי בקשות נוספות)
SMALL_DIM = 768
CACHE_DIR = ROOT / "data" / "emb_cache" / f"{MODEL}_{DIM}"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:batchEmbedContents"
BATCH_SIZE = 100      # כמה טקסטים בבקשה אחת. יורד אוטומטית אם השרת מסרב
MAX_429_IN_A_ROW = 10 # אחרי כך עוצרים ושומרים, וממשיכים בהרצה הבאה
SAMPLE_BASE = 900     # לבדיקה המוקטנת (--sample)

# הפורמט שגוגל ממליצה עליו ל-gemini-embedding-2 (אין task_type, יש קידומת)
QUERY_FORMATS = {
    "search": "task: search result | query: {q}",
    "qa": "task: question answering | query: {q}",
}
def doc_format(chunk):
    return f"title: {chunk['title']} | text: {chunk['text']}"


class Stop(Exception):
    """תקלה שבגללה עוצרים (ההטמעות שכבר התקבלו שמורות)."""


# ---------- חיפוש מילים ----------
def trigrams(text):
    out = []
    for word in re.findall(r"\w+", text.lower()):
        word = f"_{word}_"
        out += [word[i:i + 3] for i in range(len(word) - 2)]
    return out


# ---------- מפתח ----------
def load_key():
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key or key == "your-key-here":
        raise Stop("לא נמצא GEMINI_API_KEY בקובץ .env")
    return key


# ---------- מטמון הטמעות ----------
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
    n = len(list(CACHE_DIR.glob("part_*.npz")))
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

def embed_all(texts, cache, key, label):
    """מטמיע את כל הטקסטים שעוד לא במטמון. שומר אחרי כל בקשה מוצלחת."""
    missing = list(dict.fromkeys(t for t in texts if text_hash(t) not in cache))
    if not missing:
        print(f"   {label}: הכל כבר במטמון ({len(texts)})")
        return
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


def measure_query_latency(key, questions):
    """כמה זמן לוקח להטמיע שאלה אחת (זה מה שהלקוח יחכה בכל שאלה). לא נשמר במטמון."""
    session, times = requests.Session(), []
    for q in questions[:5]:
        start = time.time()
        result = call_api(session, key, [QUERY_FORMATS["search"].format(q=q)])
        if result[0] == "ok":
            times.append(time.time() - start)
    return times


# ---------- דירוג ומדדים ----------
def normalize(m):
    return m / np.linalg.norm(m, axis=-1, keepdims=True)

def rrf(*rankings, k=60):
    score = {}
    for ranking in rankings:
        for pos, idx in enumerate(ranking):
            score[idx] = score.get(idx, 0) + 1 / (k + pos + 1)
    return sorted(score, key=lambda i: -score[i])

def evaluate(name, rank_fn, chunks, answerable):
    hit1 = hit5 = 0
    rr, misses = 0.0, []
    for item in answerable:
        ranking = rank_fn(item["q"])[:10]
        ok = [any(t in chunks[i]["url"] for t in item["url"].split("|")) for i in ranking]
        hit1 += ok[0]
        hit5 += any(ok[:5])
        rr += next((1 / (p + 1) for p, good in enumerate(ok) if good), 0)
        if not any(ok[:5]):
            misses.append({"q": item["q"], "expected": item["url"],
                           "got": [chunks[i]["url"].split(".co.il")[1] for i in ranking[:3]]})
    n = len(answerable)
    return {"name": name, "hit1": hit1, "hit5": hit5, "mrr": round(rr / n, 3), "n": n, "misses": misses}

def refusal_check(name, top_score_fn, answerable, unanswerable):
    """האם ציון התוצאה הראשונה מפריד בין שאלה שיש לה תשובה לשאלה שאין?"""
    yes = [top_score_fn(a["q"]) for a in answerable]
    no = [top_score_fn(q) for q in unanswerable]
    best = None
    for t in sorted(set(yes + no)):
        correct = sum(s >= t for s in yes) + sum(s < t for s in no)
        if best is None or correct > best[1]:
            best = (t, correct)
    return {"name": name,
            "answerable_min": round(min(yes), 3), "answerable_median": round(float(np.median(yes)), 3),
            "unanswerable_max": round(max(no), 3), "unanswerable_median": round(float(np.median(no)), 3),
            "best_threshold": round(best[0], 3), "correct_at_best": best[1], "total": len(yes) + len(no),
            "unanswerable_scores": {q: round(s, 3) for q, s in zip(unanswerable, no)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword-only", action="store_true", help="רק חיפוש מילים, בלי Gemini")
    parser.add_argument("--sample", action="store_true",
                        help=f"בדיקה מוקטנת: {SAMPLE_BASE} הפסקאות הראשונות + הפסקאות של העמודים הנכונים")
    args = parser.parse_args()

    chunks = [json.loads(line) for line in CHUNKS_FILE.open(encoding="utf-8")]
    qs = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    answerable, unanswerable = qs["answerable"], qs["unanswerable"]
    if args.sample:
        # כל השיטות מחפשות באותה קבוצה, אז ההשוואה ביניהן הוגנת.
        # המספרים עצמם אופטימיים: פחות פסקאות "מבלבלות" מאשר באתר המלא.
        targets = [t for a in answerable for t in a["url"].split("|")]
        chunks = [c for i, c in enumerate(chunks)
                  if i < SAMPLE_BASE or any(t in c["url"] for t in targets)]
        print(f"🔬 בדיקה מוקטנת (--sample): {len(chunks)} פסקאות")
        global RESULTS_FILE
        RESULTS_FILE = ROOT / "eval" / "results_search_sample.json"

    # בדיקת תקינות: לכל שאלה יש באמת עמוד נכון בנתונים
    for item in answerable:
        if not any(t in c["url"] for c in chunks for t in item["url"].split("|")):
            sys.exit(f"🛑 לשאלה '{item['q']}' אין עמוד מתאים בנתונים ({item['url']}). תקני את questions.json")
    print(f"📄 {len(chunks)} פסקאות | {len(answerable)} שאלות עם תשובה | {len(unanswerable)} בלי תשובה\n")

    results, refusals, timing = [], [], {}

    # 1. מילים
    start = time.time()
    bm25 = BM25Okapi([trigrams(c["text"]) for c in chunks])
    timing["keyword_build_sec"] = round(time.time() - start, 2)
    def kw_rank(q):
        return list(np.argsort(-bm25.get_scores(trigrams(q))))
    start = time.time()
    results.append(evaluate("מילים (טריגרמות)", kw_rank, chunks, answerable))
    timing["keyword_search_ms"] = round((time.time() - start) / len(answerable) * 1000, 1)

    if not args.keyword_only:
        try:
            key = load_key()
            cache = load_cache()
            print("🧠 הטמעות Gemini:")
            doc_texts = [doc_format(c) for c in chunks]
            all_q = [a["q"] for a in answerable] + unanswerable
            embed_all(doc_texts, cache, key, "פסקאות")
            for fmt_name, fmt in QUERY_FORMATS.items():
                embed_all([fmt.format(q=q) for q in all_q], cache, key, f"שאלות ({fmt_name})")
        except Stop as e:
            print(f"\n🛑 {e}\n   מציגה רק את מה שאפשר בלי Gemini.\n")
            cache = None

        if cache is not None:
            docs = normalize(np.stack([cache[text_hash(t)] for t in doc_texts]))
            small = normalize(docs[:, :SMALL_DIM])
            timing["index_size_mb_full"] = round(docs.nbytes / 1e6, 1)
            timing["index_size_mb_768"] = round(small.nbytes / 1e6, 1)
            try:
                lat = measure_query_latency(key, all_q)
                if lat:
                    timing["query_embed_ms_median"] = round(float(np.median(lat)) * 1000)
            except Stop as e:
                print(f"   (מדידת זמן לשאלה נכשלה: {e})")

            def sem(fmt, matrix):
                def scores(q):
                    v = normalize(cache[text_hash(QUERY_FORMATS[fmt].format(q=q))][:matrix.shape[1]])
                    return matrix @ v
                return scores

            for fmt in QUERY_FORMATS:
                for dim_name, matrix in ((str(DIM), docs), (str(SMALL_DIM), small)):
                    s = sem(fmt, matrix)
                    name = f"משמעות ({fmt}, {dim_name})"
                    results.append(evaluate(name, lambda q, s=s: list(np.argsort(-s(q))), chunks, answerable))
                    refusals.append(refusal_check(name, lambda q, s=s: float(s(q).max()), answerable, unanswerable))
                    results.append(evaluate(f"שילוב ({fmt}, {dim_name})",
                                            lambda q, s=s: rrf(kw_rank(q), list(np.argsort(-s(q)))),
                                            chunks, answerable))
            start = time.time()
            for _ in range(100):
                docs @ docs[0]
            timing["semantic_search_ms_full"] = round((time.time() - start) * 10, 2)

    # ---------- דוח ----------
    print(f"{'שיטה':32} {'Hit@1':>7} {'Hit@5':>7} {'MRR':>6}")
    for r in results:
        print(f"{r['name']:32} {r['hit1']:>3}/{r['n']:<3} {r['hit5']:>3}/{r['n']:<3} {r['mrr']:>6}")
    if refusals:
        print("\nסירוב: ציון התוצאה הראשונה (דמיון, 0 עד 1)")
        print(f"{'שיטה':32} {'עם תשובה: מינ׳/חציון':>22} {'בלי תשובה: מקס׳/חציון':>22} {'סף הכי טוב':>18}")
        for f in refusals:
            print(f"{f['name']:32} {f['answerable_min']:>10} / {f['answerable_median']:<9} "
                  f"{f['unanswerable_max']:>10} / {f['unanswerable_median']:<9} "
                  f"{f['best_threshold']:>7} ({f['correct_at_best']}/{f['total']} נכון)")
    print("\nזמנים:", timing)
    for r in results:
        if r["misses"]:
            print(f"\n❌ פספוסים - {r['name']}:")
            for m in r["misses"]:
                print(f"   {m['q']}  (צפוי: {m['expected']})\n      קיבלנו: {m['got']}")

    RESULTS_FILE.write_text(json.dumps({"results": results, "refusal": refusals, "timing": timing},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n💾 נשמר ל: {RESULTS_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

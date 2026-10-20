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
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# הקוד של Gemini (מפתח, מטמון, בקשות) משותף עם בניית האינדקס והחיפוש
from core.embeddings import (  # noqa: F401 - חלק מהשמות משמשים את make_questions.py
                             DIM, INDEX_DIM, CACHE_DIR, QUERY_FORMATS, Stop, call_api, doc_format,
                             embed_all, load_cache, load_key, normalize, parse_429, text_hash)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CHUNKS_FILE = ROOT / "data" / "chunks.jsonl"
QUESTIONS_FILE = ROOT / "eval" / "questions.json"
RESULTS_FILE = ROOT / "eval" / "results_search.json"
SMALL_DIM = INDEX_DIM
SAMPLE_BASE = 900     # לבדיקה המוקטנת (--sample)


# ---------- חיפוש מילים ----------
def trigrams(text):
    out = []
    for word in re.findall(r"\w+", text.lower()):
        word = f"_{word}_"
        out += [word[i:i + 3] for i in range(len(word) - 2)]
    return out


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
def rrf(rankings, weights, k=60):
    """איחוד דירוגים (Reciprocal Rank Fusion). משקל קטן = השיטה משפיעה פחות."""
    score = {}
    for ranking, w in zip(rankings, weights):
        for pos, idx in enumerate(ranking):
            score[idx] = score.get(idx, 0) + w / (k + pos + 1)
    return sorted(score, key=lambda i: -score[i])

def is_match(item, url):
    """exact: הכתובת חייבת להיות בדיוק העמוד (לשאלות שנוצרו אוטומטית).
    אחרת: חלק מהכתובת, ו-| מפריד בין כמה עמודים נכונים (לשאלות הידניות)."""
    path = url.split(".co.il")[1]
    if item.get("exact"):
        return path == item["url"]
    return any(t in url for t in item["url"].split("|"))

def evaluate(name, rank_fn, chunks, answerable):
    hit1 = hit5 = 0
    rr, misses, groups = 0.0, [], {}
    for item in answerable:
        ranking = rank_fn(item["q"])[:10]
        ok = [is_match(item, chunks[i]["url"]) for i in ranking]
        hit1 += ok[0]
        hit5 += any(ok[:5])
        g = groups.setdefault(item.get("group", "ידני"), [0, 0, 0])
        g[0] += ok[0]; g[1] += any(ok[:5]); g[2] += 1
        rr += next((1 / (p + 1) for p, good in enumerate(ok) if good), 0)
        if not any(ok[:5]):
            misses.append({"q": item["q"], "expected": item["url"], "group": item.get("group", "ידני"),
                           "got": [chunks[i]["url"].split(".co.il")[1] for i in ranking[:3]]})
    n = len(answerable)
    return {"name": name, "hit1": hit1, "hit5": hit5, "mrr": round(rr / n, 3), "n": n,
            "groups": groups, "misses": misses}

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
    parser.add_argument("--formats", default=",".join(QUERY_FORMATS),
                        help="אילו ניסוחי שאלה לבדוק (search,qa). פחות ניסוחים = פחות בקשות")
    parser.add_argument("--questions", default=str(QUESTIONS_FILE),
                        help="קובץ השאלות (ברירת מחדל: eval/questions.json)")
    args = parser.parse_args()
    formats = [f for f in args.formats.split(",") if f in QUERY_FORMATS]
    global RESULTS_FILE
    questions_file = Path(args.questions)
    if questions_file.resolve() != QUESTIONS_FILE.resolve():
        RESULTS_FILE = ROOT / "eval" / f"results_{questions_file.stem}.json"

    chunks = [json.loads(line) for line in CHUNKS_FILE.open(encoding="utf-8")]
    qs = json.loads(questions_file.read_text(encoding="utf-8"))
    answerable, unanswerable = qs["answerable"], qs["unanswerable"]
    if args.sample:
        # כל השיטות מחפשות באותה קבוצה, אז ההשוואה ביניהן הוגנת.
        # המספרים עצמם אופטימיים: פחות פסקאות "מבלבלות" מאשר באתר המלא.
        chunks = [c for i, c in enumerate(chunks)
                  if i < SAMPLE_BASE or any(is_match(a, c["url"]) for a in answerable)]
        print(f"🔬 בדיקה מוקטנת (--sample): {len(chunks)} פסקאות")
        RESULTS_FILE = ROOT / "eval" / "results_search_sample.json"

    # בדיקת תקינות: לכל שאלה יש באמת עמוד נכון בנתונים
    for item in answerable:
        if not any(is_match(item, c["url"]) for c in chunks):
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
            for fmt_name in formats:
                fmt = QUERY_FORMATS[fmt_name]
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

            for fmt in formats:
                for dim_name, matrix in ((str(DIM), docs), (str(SMALL_DIM), small)):
                    s = sem(fmt, matrix)
                    name = f"משמעות ({fmt}, {dim_name})"
                    results.append(evaluate(name, lambda q, s=s: list(np.argsort(-s(q))), chunks, answerable))
                    refusals.append(refusal_check(name, lambda q, s=s: float(s(q).max()), answerable, unanswerable))
                    for label, w_kw in (("שילוב", 1.0), ("שילוב חצי", 0.5)):
                        results.append(evaluate(f"{label} ({fmt}, {dim_name})",
                                                lambda q, s=s, w=w_kw: rrf([kw_rank(q), list(np.argsort(-s(q)))],
                                                                           [w, 1.0]),
                                                chunks, answerable))
            start = time.time()
            for _ in range(100):
                docs @ docs[0]
            timing["semantic_search_ms_full"] = round((time.time() - start) * 10, 2)

    # ---------- דוח ----------
    print(f"{'שיטה':32} {'Hit@1':>7} {'Hit@5':>7} {'MRR':>6}")
    for r in results:
        print(f"{r['name']:32} {r['hit1']:>3}/{r['n']:<3} {r['hit5']:>3}/{r['n']:<3} {r['mrr']:>6}")
    group_names = list(results[0]["groups"])
    if len(group_names) > 1:
        print("\nלפי קבוצה - Hit@5 (בסוגריים Hit@1):")
        print(f"{'שיטה':32} " + " ".join(f"{g:>14}" for g in group_names))
        for r in results:
            cells = [f"{r['groups'][g][1]}/{r['groups'][g][2]} ({r['groups'][g][0]})" for g in group_names]
            print(f"{r['name']:32} " + " ".join(f"{c:>14}" for c in cells))
    if refusals:
        print("\nסירוב: ציון התוצאה הראשונה (דמיון, 0 עד 1)")
        print(f"{'שיטה':32} {'עם תשובה: מינ׳/חציון':>22} {'בלי תשובה: מקס׳/חציון':>22} {'סף הכי טוב':>18}")
        for f in refusals:
            print(f"{f['name']:32} {f['answerable_min']:>10} / {f['answerable_median']:<9} "
                  f"{f['unanswerable_max']:>10} / {f['unanswerable_median']:<9} "
                  f"{f['best_threshold']:>7} ({f['correct_at_best']}/{f['total']} נכון)")
    print("\nזמנים:", timing)
    for r in results:
        if r["misses"] and (len(r["misses"]) <= 12 or r["name"].startswith("משמעות (") and r["name"].endswith(", 768)")):
            print(f"\n❌ פספוסים - {r['name']}:")
            for m in r["misses"]:
                print(f"   {m['q']}  (צפוי: {m['expected']})\n      קיבלנו: {m['got']}")

    RESULTS_FILE.write_text(json.dumps({"results": results, "refusal": refusals, "timing": timing},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n💾 נשמר ל: {RESULTS_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

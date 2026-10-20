"""
שלב 3-4: בדיקת הבוט כולו (חיפוש + מודל שפה) על שאלות הבדיקה.

מה נבדק:
  - שאלות עם תשובה (מדגם מ-eval/questions_full.json): האם הבוט ענה, והאם צירף את העמוד הנכון כמקור.
  - 20 שאלות בלי תשובה באתר: האם הבוט סירב (ולא המציא).
  - שיחות (eval/dialogues.json): שאלות המשך, החלפת נושא, שאלת הבהרה, פוליסה אישית.
כל התשובות נשמרות לקריאה ידנית - המספרים לא אומרים אם התוכן נכון, רק אם הבוט התנהג נכון.

הרצה:
  python eval/run_eval.py                       # מצב רגיל
  python eval/run_eval.py --retrieval keywords  # בדיקת גיבוי החיפוש (מילים)
  python eval/run_eval.py --model gemini-3.5-flash  # בדיקת מודל אחר
אפשר לעצור ולהריץ שוב: תשובות שכבר התקבלו נשמרות וההרצה ממשיכה.
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import answer as answer_module, llm  # noqa: E402
from core.answer import answer  # noqa: E402
from core.retriever import Retriever  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

QUESTIONS_FILE = ROOT / "eval" / "questions_full.json"
DIALOGUES_FILE = ROOT / "eval" / "dialogues.json"
N_ANSWERABLE = 40
SEED = 7


def matches(url, expected, exact):
    path = url.split(".co.il")[1] if ".co.il" in url else url
    if exact:
        return path == expected
    return any(t in url for t in expected.split("|"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval", default="vectors", choices=["vectors", "keywords"])
    parser.add_argument("--model", default=llm.DEFAULT_MODEL)
    parser.add_argument("--n", type=int, default=N_ANSWERABLE, help="כמה שאלות עם תשובה לבדוק")
    args = parser.parse_args()
    out_file = ROOT / "eval" / f"results_answers_{args.retrieval}_{args.model}.jsonl"

    # שאלות הבדיקה כבר הוטמעו בבדיקת החיפוש: לוקחים אותן מהמטמון ולא מבזבזים מכסה
    answer_module._retriever = Retriever(use_cache=True)
    qs = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    sample = random.Random(SEED).sample(qs["answerable"], min(args.n, len(qs["answerable"])))
    dialogues = json.loads(DIALOGUES_FILE.read_text(encoding="utf-8"))["dialogues"]

    done = {}
    if out_file.exists():
        for line in out_file.open(encoding="utf-8"):
            row = json.loads(line)
            done[row["key"]] = row
    print(f"🧪 {args.retrieval} + {args.model} | {len(done)} תשובות כבר שמורות")

    def run(key, question, history=None, **meta):
        if key in done:
            return done[key]
        start = time.time()
        res = answer(question, history=history, model=args.model, retrieval=args.retrieval)
        row = dict(key=key, seconds=round(time.time() - start, 1), **meta, **res)
        done[key] = row
        with out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"   {row['status']:11} {row['seconds']:>5}s (חיפוש {row.get('t_search', '-')}s, מודל {row.get('t_llm', '-')}s)"
              f" | {question[:60]}")
        if res["status"] == "unavailable":
            raise SystemExit(f"\n🛑 השירות לא זמין ({res.get('reason')}). מריצים שוב מאוחר יותר - ממשיך מאיפה שעצר.")
        return row

    for a in sample:
        run("A|" + a["q"], a["q"], kind="answerable", group=a.get("group", "ידני"),
            expected=a["url"], exact=a.get("exact", False))
    for q in qs["unanswerable"]:
        run("U|" + q, q, kind="unanswerable")
    for d in dialogues:
        history = []
        for i, t in enumerate(d["turns"]):
            row = run(f"D|{d['name']}|{i}", t["q"], history=list(history), kind="dialogue",
                      dialogue=d["name"], turn=i, expect=t["expect"], expected=t.get("url"))
            history += [{"role": "user", "text": t["q"]}, {"role": "assistant", "text": row["answer"]}]

    # ---------- סיכום ----------
    rows = list(done.values())
    A = [r for r in rows if r["kind"] == "answerable"]
    U = [r for r in rows if r["kind"] == "unanswerable"]
    D = [r for r in rows if r["kind"] == "dialogue"]

    def count(rs, status):
        return sum(r["status"] == status for r in rs)
    right_source = sum(r["status"] == "answer" and any(matches(s["url"], r["expected"], r["exact"]) for s in r["sources"])
                       for r in A)
    print(f"\n=== שאלות עם תשובה ({len(A)}) ===")
    print(f"   ענה: {count(A, 'answer')} | ענה עם העמוד הצפוי כמקור: {right_source} | "
          f"סירב: {count(A, 'not_found')} | ביקש הבהרה: {count(A, 'clarify')}")
    print(f"=== שאלות בלי תשובה באתר ({len(U)}) ===")
    print(f"   סירב: {count(U, 'not_found')} | ביקש הבהרה: {count(U, 'clarify')} | ענה: {count(U, 'answer')}")
    for r in U:
        if r["status"] == "answer":
            print(f"   ⚠️ ענה על: {r['question']}\n      {r['answer'][:200]}")
    print(f"=== שיחות ({len(D)} תורות) ===")
    for r in D:
        mark = "✅" if (r["expect"] == r["status"] or (r["expect"] == "answer_or_not_found" and r["status"] in ("answer", "not_found"))
                       or (r["expect"] == "personal" and r["status"] == "answer")) else "❓"
        src = ", ".join(s["url"].split(".co.il")[1][:45] for s in r["sources"])
        print(f"   {mark} {r['dialogue']} | תור {r['turn'] + 1}: {r['status']} (צפוי {r['expect']})")
        print(f"      חיפשנו: {r['search_query']}\n      ענה: {r['answer'][:180]}\n      מקורות: {src}")
    secs = sorted(r["seconds"] for r in rows)
    print(f"\n⏱️ זמן לתשובה: חציון {secs[len(secs) // 2]}s, מקסימום {secs[-1]}s | חיפוש: "
          + ", ".join(f"{k}={sum(r.get('retrieval') == k for r in rows)}" for k in ("vectors", "keywords")))
    print(f"💾 כל התשובות: {out_file.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

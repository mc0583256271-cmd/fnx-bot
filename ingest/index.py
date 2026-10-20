"""
שלב 2: בניית האינדקס הסמנטי.

מה זה עושה:
  1. קורא את הפסקאות (data/chunks.jsonl).
  2. לכל פסקה צריך וקטור מ-Gemini (gemini-embedding-2). וקטורים של טקסט שכבר
     הוטמע נלקחים מהמטמון (data/emb_cache/) - רק פסקאות חדשות או ששונו נשלחות לגוגל.
  3. מקצר כל וקטור ל-768 ומנרמל (נבדק: איכות זהה ל-3072, קטן פי 4).
  4. שומר את האינדקס ב-data/index/:
       vectors.npy     - מטריצה: שורה לכל פסקה
       chunks.jsonl    - הפסקאות עצמן, באותו סדר (כתובת, כותרת, טקסט)
       manifest.json   - מתי נבנה, מאיזה מודל, כמה פסקאות

הרצה (מתיקיית הפרויקט):
  python ingest/index.py             # בונה אינדקס מהפסקאות הקיימות
  python ingest/index.py --refresh   # רענון מלא: סריקה -> חיתוך -> אינדקס (מה שכפתור המנהל יריץ)

הגנות - האינדקס הקודם נשאר כמו שהוא אם:
  - חסרים וקטורים (נגמרה המכסה, אין רשת). מריצים שוב, וההרצה ממשיכה מאיפה שעצרה.
  - יש פחות מ-90% מהפסקאות של האינדקס הקודם (כנראה הסריקה נכשלה).
  - הסריקה או החיתוך נכשלו (ב---refresh).
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.embeddings import (INDEX_DIM, MODEL, QUERY_FORMAT, Stop, doc_format, embed_all,  # noqa: E402
                             load_cache, load_key, text_hash, to_index_dim)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CHUNKS_FILE = ROOT / "data" / "chunks.jsonl"
INDEX_DIR = ROOT / "data" / "index"
VECTORS_FILE = INDEX_DIR / "vectors.npy"
META_FILE = INDEX_DIR / "chunks.jsonl"
MANIFEST_FILE = INDEX_DIR / "manifest.json"
MIN_CHUNKS_RATIO = 0.9
META_FIELDS = ["chunk_id", "url", "title", "breadcrumb", "section", "topic", "lastmod", "crawled_at",
               "word_count", "text", "body"]


def run_step(script):
    """מריץ שלב קודם (סריקה / חיתוך). אם הוא נכשל - עוצרים בלי לגעת באינדקס."""
    print(f"\n▶ {script}")
    result = subprocess.run([sys.executable, str(ROOT / "ingest" / script)], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"🛑 {script} נכשל (קוד {result.returncode}). האינדקס הקודם נשאר כמו שהוא.")


def previous_manifest():
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_atomic(path, write_fn):
    """כותבים לקובץ זמני ומחליפים בבת אחת - אין מצב של קובץ חצי כתוב."""
    tmp = path.with_name(path.name + ".tmp")
    write_fn(tmp)
    tmp.replace(path)


def build(force=False):
    chunks = [json.loads(line) for line in CHUNKS_FILE.open(encoding="utf-8")]
    if not chunks:
        sys.exit("🛑 אין פסקאות ב-data/chunks.jsonl")
    ids = [c["chunk_id"] for c in chunks]
    if len(set(ids)) != len(ids):
        sys.exit("🛑 יש chunk_id כפול ב-data/chunks.jsonl - מריצים שוב את chunk.py")

    prev = previous_manifest()
    if prev and not force and len(chunks) < MIN_CHUNKS_RATIO * prev["chunks"]:
        sys.exit(f"🛑 רק {len(chunks)} פסקאות לעומת {prev['chunks']} באינדקס הקודם (פחות מ-90%). "
                 "כנראה הסריקה נכשלה. האינדקס הקודם נשאר. (להכריח: --force)")

    texts = [doc_format(c) for c in chunks]
    cache = load_cache()
    print(f"📄 {len(chunks)} פסקאות מ-{len({c['url'] for c in chunks})} עמודים")
    try:
        new = embed_all(texts, cache, load_key(), "וקטורים לפסקאות")
    except Stop as e:
        have = sum(text_hash(t) in cache for t in texts)
        sys.exit(f"🛑 {e}\n   יש וקטורים ל-{have} מתוך {len(texts)}. האינדקס הקודם נשאר כמו שהוא; "
                 "הריצי שוב מאוחר יותר והבנייה תמשיך מאיפה שעצרה.")

    vectors = to_index_dim(np.stack([cache[text_hash(t)] for t in texts]))
    if not np.isfinite(vectors).all() or vectors.shape != (len(chunks), INDEX_DIM):
        sys.exit("🛑 וקטורים לא תקינים - האינדקס לא נשמר")

    removed = None
    if prev and META_FILE.exists():
        old_ids = {json.loads(line)["chunk_id"] for line in META_FILE.open(encoding="utf-8")}
        removed = len(old_ids - set(ids))

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL, "dim": INDEX_DIM, "query_format": QUERY_FORMAT,
        "chunks": len(chunks), "pages": len({c["url"] for c in chunks}),
        "newest_crawl": max(c.get("crawled_at") or "" for c in chunks),
        "vectors_sha1": hashlib.sha1(vectors.tobytes()).hexdigest(),
    }
    # הסדר חשוב: קודם הנתונים, ה-manifest אחרון. החיפוש בודק שהשלושה תואמים.
    def save_vectors(path):
        with open(path, "wb") as f:  # הקובץ נסגר לפני ההחלפה (ב-Windows אי אפשר להחליף קובץ פתוח)
            np.save(f, vectors)
    write_atomic(VECTORS_FILE, save_vectors)
    write_atomic(META_FILE, lambda p: p.write_text(
        "".join(json.dumps({k: c.get(k) for k in META_FIELDS}, ensure_ascii=False) + "\n" for c in chunks),
        encoding="utf-8"))
    write_atomic(MANIFEST_FILE, lambda p: p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                                       encoding="utf-8"))

    print(f"\n✅ אינדקס נבנה: {len(chunks)} פסקאות, {manifest['pages']} עמודים, וקטורים בגודל {INDEX_DIM}")
    print(f"   וקטורים חדשים מגוגל: {new}" + (f" | פסקאות שהוסרו מהאינדקס הקודם: {removed}" if removed is not None else ""))
    print(f"   גודל: {VECTORS_FILE.stat().st_size / 1e6:.1f}MB | נשמר ל: {INDEX_DIR}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="רענון מלא: crawl.py, chunk.py ואז אינדקס")
    parser.add_argument("--force", action="store_true", help="לבנות גם אם יש הרבה פחות פסקאות מקודם")
    args = parser.parse_args()
    if args.refresh:
        run_step("crawl.py")
        run_step("chunk.py")
    build(force=args.force)


if __name__ == "__main__":
    main()

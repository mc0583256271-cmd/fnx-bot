"""
חיפוש הפסקאות הרלוונטיות לשאלה (שלב 2 - האחזור).

איך נבחרות הפסקאות:
  1. השאלה הופכת לווקטור (Gemini, אותו מודל כמו הפסקאות, עם הקידומת "task: search result").
  2. מחשבים דמיון קוסינוס בין השאלה לכל 2,405 הפסקאות (מכפלת מטריצה, פחות מאלפית שנייה).
  3. מחזירים את 8 הפסקאות הכי קרובות, עם הציון של כל אחת.

למה 8 ולא 5: בבדיקה על 154 שאלות, 5 הפסקאות הראשונות הגיעו בממוצע מ-3.5 עמודים בלבד
(כמה פסקאות מאותו עמוד). עם 8 העמוד הנכון נמצא ב-91 מתוך 100 שאלות אקראיות (מול 87 עם 5).

שימוש:
  from core.retriever import Retriever
  r = Retriever()
  for hit in r.search("איך מגישים תביעה על נזקי מים?"):
      print(hit["score"], hit["url"], hit["title"])
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.embeddings import (INDEX_DIM, MODEL, QUERY_FORMAT, Stop, call_api, load_cache,  # noqa: E402
                             load_key, query_format, text_hash, to_index_dim)

INDEX_DIR = ROOT / "data" / "index"
TOP_K = 8


class IndexNotReady(Exception):
    """האינדקס חסר או לא תקין - צריך להריץ python ingest/index.py"""


class Retriever:
    def __init__(self, index_dir=INDEX_DIR, use_cache=False):
        index_dir = Path(index_dir)
        try:
            manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
            vectors = np.load(index_dir / "vectors.npy")
            chunks = [json.loads(line) for line in (index_dir / "chunks.jsonl").open(encoding="utf-8")]
        except FileNotFoundError:
            raise IndexNotReady("אין אינדקס. מריצים: python ingest/index.py")
        except (ValueError, OSError):  # קובץ פגום (JSON שבור, npy חלקי)
            raise IndexNotReady("קובץ אינדקס פגום. מריצים שוב: python ingest/index.py")
        # בדיקת התאמה: שלושת הקבצים נבנו יחד, מאותו מודל, באותו גודל
        try:
            ok = (manifest["model"] == MODEL and manifest["dim"] == INDEX_DIM
                  and manifest["query_format"] == QUERY_FORMAT
                  and vectors.shape == (manifest["chunks"], INDEX_DIM) and len(chunks) == manifest["chunks"]
                  and hashlib.sha1(vectors.tobytes()).hexdigest() == manifest["vectors_sha1"])
        except (KeyError, TypeError):
            ok = False
        if not ok:
            raise IndexNotReady("קבצי האינדקס לא תואמים זה לזה או לקוד. מריצים שוב: python ingest/index.py")
        self.manifest, self.vectors, self.chunks = manifest, vectors, chunks
        # use_cache=True: שאלות שכבר הוטמעו נלקחות מהמטמון (לבדיקות - חוסך מכסה).
        # בבוט עצמו: שאלה חדשה נשמרת בזיכרון בלבד, לא בדיסק.
        self.cache = load_cache() if use_cache else {}
        self._key = None
        self._session = requests.Session()

    def embed_question(self, question):
        text = query_format(question)
        h = text_hash(text)
        if h not in self.cache:
            if self._key is None:
                self._key = load_key()
            result = call_api(self._session, self._key, [text])
            if result[0] != "ok":
                raise Stop("Gemini לא זמין כרגע (מגבלת קצב או מכסה). נסו שוב בעוד דקה.")
            self.cache[h] = np.array(result[1][0], dtype=np.float32)
        return to_index_dim(self.cache[h])

    def search(self, question, k=TOP_K):
        """מחזיר רשימה של k פסקאות, מהקרובה ביותר: score, url, title, breadcrumb, body ועוד."""
        scores = self.vectors @ self.embed_question(question)
        top = np.argsort(-scores)[:k]
        return [dict(self.chunks[i], score=round(float(scores[i]), 4)) for i in top]

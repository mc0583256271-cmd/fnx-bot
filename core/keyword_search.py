"""
חיפוש לפי מילים (BM25 על שלישיות אותיות) - גיבוי בלבד.

החיפוש הרגיל הוא וקטורים (core/retriever.py). את זה משתמשים רק כשאי אפשר לקבל וקטור
לשאלה (נגמרה המכסה, אין רשת). בבדיקה הוא מצא את העמוד הנכון ב-115/154 (וקטורים: 140/154).
שלישיות אותיות במקום מילים שלמות: בעברית "בביטוח", "לביטוח", "הביטוח" חולקים את רוב השלישיות.
"""
import re

import numpy as np
from rank_bm25 import BM25Okapi


def trigrams(text):
    out = []
    for word in re.findall(r"\w+", text.lower()):
        word = f"_{word}_"
        out += [word[i:i + 3] for i in range(len(word) - 2)]
    return out


class KeywordSearch:
    def __init__(self, chunks):
        self.chunks = chunks
        self.bm25 = BM25Okapi([trigrams(c["text"]) for c in chunks])  # כשנייה וחצי

    def search(self, question, k=8):
        scores = self.bm25.get_scores(trigrams(question))
        top = np.argsort(-scores)[:k]
        # ציון BM25 לא בסולם של 0 עד 1 ולא משמש להחלטה על סירוב - רק לסדר
        return [dict(self.chunks[i], score=round(float(scores[i]), 4)) for i in top]

"""
מודל השפה (Gemini) - בקשה אחת שמחזירה JSON.

- מודל ראשי: gemini-3.1-flash-lite (נבחר: מכסה חינמית שהספיקה לכ-100 בקשות ביום הבדיקה).
- אם המודל עמוס (503) או שהמכסה שלו נגמרה - Unavailable. מה עושים אז מחליט מי שקורא לנו.
  (מודל גיבוי ייכנס רק אחרי שייבדק ב-eval/run_eval.py שהוא לא מייצר תשובות שגויות.)
"""
import json
import time

import requests

from core.embeddings import load_key, parse_429

DEFAULT_MODEL = "gemini-3.1-flash-lite"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class Unavailable(Exception):
    """מודל השפה לא זמין כרגע (מכסה, עומס, רשת)."""


_session = requests.Session()
_key = None


def generate_json(system, user, model=DEFAULT_MODEL, temperature=0.2, max_wait=40):
    """שולח הוראות מערכת + הודעה, ומחזיר dict. ממתין לכל היותר max_wait שניות על מגבלת קצב."""
    global _key
    if _key is None:
        _key = load_key()
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    waited = 0
    for attempt in range(4):
        try:
            r = _session.post(URL.format(model=model), json=body, headers={"x-goog-api-key": _key}, timeout=60)
        except requests.RequestException as e:
            if attempt == 3:
                raise Unavailable(f"בעיית רשת: {type(e).__name__}")
            time.sleep(3)
            continue
        if r.status_code == 200:
            try:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            except Exception:
                if attempt == 3:
                    raise Unavailable("המודל החזיר תשובה לא תקינה")
                continue
        if r.status_code == 429:
            delay, quota = parse_429(r)
            if "PerDay" in quota or waited + delay > max_wait:
                raise Unavailable(f"מגבלת שימוש ({quota})")
            time.sleep(delay + 1)
            waited += delay + 1
            continue
        if r.status_code >= 500:
            time.sleep(3)
            continue
        raise Unavailable(f"{model} החזיר {r.status_code}: " + r.text[:150].replace("\n", " "))
    raise Unavailable(f"{model} עמוס")

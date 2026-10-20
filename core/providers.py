"""
ספקי מודל שפה - מבנה מונחה עצמים, כדי שאפשר יהיה להחליף ספק או מודל בלי לגעת בשאר הקוד.

  LLMProvider       מחלקה בסיסית: generate(system, user) -> (dict, שם המודל שענה), או Unavailable.
  GeminiProvider    מודל אחד של Gemini (מודל, רמת חשיבה, מגבלת זמן).
  FallbackProvider  רשימת ספקים: מנסה לפי הסדר, ועובר מיד לבא בתור כשאחד נכשל.

להוסיף ספק חדש (כמו ClaudeProvider, או מפתח Gemini בתשלום) = מחלקה יורשת חדשה שמממשת generate,
והוספה שלה לרשימה ב-default_provider(). שום דבר ב-answer.py לא משתנה.

למה רשימה: ה-API החינמי של Gemini מחזיר לפעמים 503 ("ביקוש גבוה") או לא עונה בכלל,
ובכל רגע מודל אחר זמין (נמדד: באותה דקה מודל אחד ענה תוך 3 שניות ואחר לא ענה תוך 30).
503 חוזר תוך 1-2 שניות, ולכן מעבר למודל הבא כמעט לא מוסיף זמן.
"""
import json
import time

import requests

from core.embeddings import load_key, parse_429


class Unavailable(Exception):
    """אף מודל לא זמין כרגע (מכסה, עומס, רשת)."""


class LLMProvider:
    """מחלקה בסיסית לכל ספק. כל ספק מחזיר JSON (dict) ואת שם המודל שענה."""
    name = "base"

    def generate(self, system, user):
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    _session = requests.Session()

    def __init__(self, model, thinking="medium", timeout=10, temperature=0.2):
        self.model, self.thinking, self.timeout, self.temperature = model, thinking, timeout, temperature
        self.name = model
        self._key = None

    def generate(self, system, user):
        if self._key is None:
            self._key = load_key()
        config = {"responseMimeType": "application/json", "temperature": self.temperature}
        if self.thinking:
            config["thinkingConfig"] = {"thinkingLevel": self.thinking}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": config}
        try:
            r = self._session.post(self.URL.format(model=self.model), json=body,
                                   headers={"x-goog-api-key": self._key}, timeout=self.timeout)
        except requests.RequestException as e:
            raise Unavailable(f"{self.model}: {type(e).__name__}")
        if r.status_code == 200:
            try:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text), self.model
            except Exception:
                raise Unavailable(f"{self.model}: תשובה לא תקינה")
        if r.status_code == 429:
            raise Unavailable(f"{self.model}: מגבלת שימוש ({parse_429(r)[1]})")
        if r.status_code >= 500:
            raise Unavailable(f"{self.model}: עמוס ({r.status_code})")
        # 400 וכו' - כנראה הגדרה לא נתמכת (למשל רמת חשיבה). לא שקט: רואים את זה בבדיקות
        raise Unavailable(f"{self.model}: {r.status_code} " + r.text[:150].replace("\n", " "))


class ClaudeProvider(LLMProvider):
    """Claude של Anthropic (Messages API). תשתית נפרדת מגוגל - גיבוי אמיתי לעומס ב-Gemini."""
    URL = "https://api.anthropic.com/v1/messages"
    _session = requests.Session()

    def __init__(self, model="claude-haiku-5-5", timeout=20, max_tokens=2000):
        # בלי temperature: Claude Haiku 5.5 מחזיר שגיאה אם שולחים אותו ("deprecated for this model")
        self.model, self.timeout, self.max_tokens = model, timeout, max_tokens
        self.name = model
        self._key = None

    def generate(self, system, user):
        if self._key is None:
            try:
                self._key = load_key("ANTHROPIC_API_KEY")
            except Exception:
                raise Unavailable(f"{self.model}: אין ANTHROPIC_API_KEY")
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "system": system, "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        try:
            r = self._session.post(self.URL, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise Unavailable(f"{self.model}: {type(e).__name__}")
        if r.status_code == 200:
            data = r.json()
            text = "".join(part.get("text", "") for part in data.get("content", [])).strip()
            if data.get("stop_reason") == "max_tokens":
                raise Unavailable(f"{self.model}: התשובה נקטעה (max_tokens)")
            try:
                if text.startswith("```"):  # לפעמים ה-JSON עטוף ב-```json ... ```
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                return json.loads(text[text.index("{"):text.rindex("}") + 1]), self.model
            except Exception as e:
                # מציגים את תחילת הטקסט כדי שאפשר יהיה להבין מה השתבש
                raise Unavailable(f"{self.model}: תשובה לא תקינה ({type(e).__name__}): "
                                  + text[:300].replace("\n", " "))
        if r.status_code in (429, 529) or r.status_code >= 500:
            raise Unavailable(f"{self.model}: עמוס או מגבלת שימוש ({r.status_code})")
        raise Unavailable(f"{self.model}: {r.status_code} " + r.text[:150].replace("\n", " "))


class FallbackProvider(LLMProvider):
    """מנסה כל ספק לפי הסדר. אם כולם נכשלו - סבב נוסף אחרי הפסקה קצרה (עד rounds סבבים)."""
    name = "fallback"

    def __init__(self, providers, rounds=2, pause=2, budget=30):
        self.providers, self.rounds, self.pause, self.budget = providers, rounds, pause, budget
        self.last_errors = []

    def generate(self, system, user):
        start, self.last_errors = time.time(), []
        for round_no in range(self.rounds):
            for p in self.providers:
                if time.time() - start > self.budget:
                    raise Unavailable("נגמר הזמן: " + " | ".join(self.last_errors[-3:]))
                t0 = time.time()
                try:
                    return p.generate(system, user)
                except Unavailable as e:
                    self.last_errors.append(f"{e} [{time.time() - t0:.1f}s]")
            if round_no + 1 < self.rounds:
                time.sleep(self.pause)
        raise Unavailable(" | ".join(self.last_errors[-3:]))


# רמת חשיבה: מתחילים ב-medium (החלטה), ואם זה איטי מדי - יורדים ל-low.
THINKING = "medium"
# (מודל, כמה שניות לחכות לו). לאחרון יותר זמן: הוא איטי (נמדד כ-25 שניות), אבל הוא המוצא האחרון.
DEFAULT_CHAIN = [("gemini-3.6-flash", 10), ("gemini-3.1-flash-lite", 10), ("gemini-flash-lite-latest", 20)]


CLAUDE_MODEL = "claude-haiku-5-5"


def default_provider():
    """Claude ראשון (אם יש מפתח), ואחריו רשימת Gemini כגיבוי."""
    chain = [GeminiProvider(m, thinking=THINKING, timeout=t) for m, t in DEFAULT_CHAIN]
    try:
        load_key("ANTHROPIC_API_KEY")
        chain.insert(0, ClaudeProvider(CLAUDE_MODEL))
    except Exception:
        pass  # בלי מפתח של Anthropic - Gemini בלבד
    return FallbackProvider(chain)

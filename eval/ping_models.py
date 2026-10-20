"""
בדיקה מהירה: כמה זמן לוקח לכל מודל לענות על שאלה קצרה (Claude ו-Gemini).
מריצים מהמחשב עצמו:  python eval/ping_models.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.providers import DEFAULT_CHAIN, ClaudeProvider, GeminiProvider, Unavailable  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

providers = [ClaudeProvider(timeout=30)] + [GeminiProvider(m, timeout=30) for m, _ in DEFAULT_CHAIN]
for p in providers:
    start = time.time()
    try:
        data, _ = p.generate('החזר JSON בלבד: {"word": "<מילה אחת בעברית>"}', "מה צבע השמיים?")
        print(f"{p.name:26} ✅ {time.time() - start:5.1f} שניות  {data}")
    except Unavailable as e:
        print(f"{p.name:26} ❌ {time.time() - start:5.1f} שניות  {e}")

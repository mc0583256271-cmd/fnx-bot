"""
רענון המידע מהאתר מתוך עמוד המנהל: מריץ ברקע את ingest/index.py --refresh (סריקה -> חיתוך -> אינדקס).

- רק רענון אחד בכל רגע (נעילה ברמת השרת, לא לכל משתמש).
- אם משהו נכשל או שהתוצאה חשודה (פחות מ-90% מהעמודים / הפסקאות) - האינדקס הקודם נשאר. הבדיקות האלה
  כבר בתוך crawl.py ו-index.py.
- כשהרענון מצליח, נכתב manifest חדש. הצ'אט טוען את האינדקס לפי built_at שב-manifest, ולכן עובר אליו לבד.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "data" / "refresh.log"


class RefreshJob:
    def __init__(self):
        self._lock = threading.Lock()
        self.process = None
        self.started = None
        self.finished = None
        self.returncode = None

    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        """מתחיל רענון. מחזיר False אם כבר רץ אחד."""
        with self._lock:
            if self.running():
                return False
            log = LOG_FILE.open("w", encoding="utf-8")
            self.process = subprocess.Popen([sys.executable, "-u", str(ROOT / "ingest" / "index.py"), "--refresh"],
                                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                            env=_env_with_keys())
            self.started, self.finished, self.returncode = time.time(), None, None
            threading.Thread(target=self._wait, args=(log,), daemon=True).start()
            return True

    def _wait(self, log):
        self.returncode = self.process.wait()
        self.finished = time.time()
        log.close()

    def log_tail(self, lines=25):
        if not LOG_FILE.exists():
            return ""
        return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _env_with_keys():
    """התהליך ברקע צריך את מפתח Gemini (להטמעת פסקאות חדשות). בענן הוא ב-Secrets ולא בסביבה."""
    import os
    from core.embeddings import Stop, load_key
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        env["GEMINI_API_KEY"] = load_key()
    except Stop:
        pass
    return env

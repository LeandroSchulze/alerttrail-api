# app/services/email_verify.py
import os, random, string
from datetime import datetime, timedelta, timezone

VERIFICATION_TTL_MIN = int(os.getenv("VERIFICATION_TTL_MIN", "15"))
RESEND_WINDOW_SEC    = int(os.getenv("VERIFICATION_RESEND_WINDOW_SEC", "60"))
MAX_VERIFY_ATTEMPTS  = int(os.getenv("MAX_VERIFY_ATTEMPTS", "6"))

def gen_code(n: int = 6) -> str:
    return "".join(random.choices(string.digits, k=n))

def expires_at(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(minutes=VERIFICATION_TTL_MIN)

"""JWT + bcrypt للوحة التحكم (bcrypt مباشرة — passlib متقادمة مع bcrypt≥4)."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def make_token(sub: str) -> str:
    s = get_settings()
    payload = {"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> str:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])["sub"]

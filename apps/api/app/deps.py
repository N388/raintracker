"""اعتماديات مشتركة: المصادقة وRate Limiting."""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address

from . import security

bearer = HTTPBearer(auto_error=False)
limiter = Limiter(key_func=get_remote_address, default_limits=["300/minute"])


def require_admin(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if creds is None:
        raise HTTPException(401, "مطلوب رمز المصادقة")
    try:
        return security.decode_token(creds.credentials)
    except Exception:
        raise HTTPException(401, "رمز غير صالح أو منتهٍ")

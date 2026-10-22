"""تطبيق FastAPI — منصة مطر."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .admin import router as admin_router
from .api_v1 import router as public_router
from .deps import limiter

app = FastAPI(title="مطر — منصة الأمطار التاريخية", version="1.0.0",
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                   allow_headers=["*"], max_age=600)

app.include_router(public_router)
app.include_router(admin_router)


@app.get("/api/v1", include_in_schema=False)
async def root():
    return {"name": "مطر", "docs": "/api/docs"}

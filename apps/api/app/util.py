"""أدوات عامة: الوقت UTC وقراءة إعدادات الوسم."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

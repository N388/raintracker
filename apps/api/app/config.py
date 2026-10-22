"""إعدادات التطبيق من متغيرات البيئة."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://rain:rain_dev_pw@localhost:5433/rain"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-insecure-change-me"
    jwt_ttl_minutes: int = 60 * 12
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me"

    earthdata_username: str = ""
    earthdata_password: str = ""

    # مصادر المطر المفعّلة (يفصل بينها فاصلة)
    rain_sources: str = "imerg_v07,chirps_v3"
    # وضع التجربة: لا جلب خارجي، توليد بيانات اصطناعية محلية
    rain_dry_run: bool = True

    qa_threshold_pct: float = 25.0

    # خدمات داخلية
    titiler_url: str = "http://localhost:8000"     # من متصفح المستخدم
    titiler_internal: str = "http://titiler:80"    # من داخل الشبكة
    martin_url: str = "http://localhost:3000"
    data_dir: str = "/data"

    bbox_west: float = 34.4
    bbox_south: float = 15.0
    bbox_east: float = 55.6
    bbox_north: float = 32.3

    @property
    def sources_list(self) -> list[str]:
        return [s.strip() for s in self.rain_sources.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

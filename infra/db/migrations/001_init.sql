-- ترميز وهوية
SET client_encoding = 'UTF8';
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- تطبيع عربي للبحث: إزالة التشكيل وتوحيد الألف والياء/الألف المقصورة والة
CREATE OR REPLACE FUNCTION normalize_ar(text) RETURNS text AS $$
  SELECT lower(
    translate(
      unaccent(regexp_replace($1, '[ً-ٟ]', '', 'g')),
      'أإآءىؤئةك', 'ااهييؤئهك'
    )
  );
$$ LANGUAGE sql IMMUTABLE;

-- إعدادات التطبيق
CREATE TABLE IF NOT EXISTS app_settings (
  key text PRIMARY KEY,
  value jsonb NOT NULL
);
INSERT INTO app_settings (key, value) VALUES
  ('wasm', '{"start": "10-16", "length_days": 52}'),
  ('qa_threshold_pct', '25'),
  ('rain_sources', '["imerg_v07", "chirps_v3"]')
ON CONFLICT (key) DO NOTHING;

-- كتالوج الطبقات
CREATE TABLE IF NOT EXISTS layers_meta (
  key text PRIMARY KEY,
  name_ar text NOT NULL,
  name_en text NOT NULL,
  group_ar text NOT NULL,
  geom_type text NOT NULL,
  minzoom int NOT NULL DEFAULT 0,
  style jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  ord int NOT NULL DEFAULT 0
);

-- جدول البحث الموحّد
CREATE TABLE IF NOT EXISTS places_search (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL,
  kind text NOT NULL,
  source text NOT NULL,
  src_id bigint,
  geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX places_search_name_trgm ON places_search USING gin (normalize_ar(name) gin_trgm_ops);
CREATE INDEX places_search_geom ON places_search USING gist (geom);

-- سجلات التشغيل والتدقيق
CREATE TABLE IF NOT EXISTS etl_runs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job text NOT NULL,
  product text,
  status text NOT NULL DEFAULT 'running',
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  stats jsonb NOT NULL DEFAULT '{}'::jsonb,
  error text
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor text NOT NULL,
  action text NOT NULL,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  role text NOT NULL DEFAULT 'admin',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE EXTENSION IF NOT EXISTS postgis_raster;

-- مخطط قلب المطر: سجل يومي (بيانات وصفية) + قيم مفكوكة هي مصدر الحقيقة الوحيد
CREATE TABLE IF NOT EXISTS rain_daily (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  day date NOT NULL,
  product text NOT NULL,           -- imerg_late / chirps_v3_daily / *_sample
  source text NOT NULL,            -- imerg_v07 / chirps_v3
  cells int NOT NULL DEFAULT 0,    -- عدد الخلايا المستوعبة
  fetched_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (day, product)
);
CREATE INDEX IF NOT EXISTS rain_daily_day_idx ON rain_daily (day);

-- القيم المفكوكة (تغذي المواد المجمّلة والاستعلامات النقطية السريعة)
CREATE TABLE IF NOT EXISTS rain_values (
  day date NOT NULL,
  source text NOT NULL,
  iy int NOT NULL,
  ix int NOT NULL,
  val real NOT NULL,
  PRIMARY KEY (source, day, iy, ix)
);
CREATE INDEX IF NOT EXISTS rain_values_cell_idx ON rain_values (source, iy, ix);

-- شبكة الخلايا لكل مصدر (بدقة المصدر الأصلية؛ لا تجانب دقّة)
CREATE TABLE IF NOT EXISTS rain_cells (
  source text NOT NULL,            -- imerg_v07 (0.1°) / chirps_v3 (0.05°)
  ix int NOT NULL,
  iy int NOT NULL,
  res double precision NOT NULL,   -- 0.1 أو 0.05
  west double precision NOT NULL,  -- 34.4
  south double precision NOT NULL, -- 15.0
  geom geometry(Point, 4326) NOT NULL,
  PRIMARY KEY (source, ix, iy)
);
CREATE INDEX rain_cells_geom_idx ON rain_cells USING gist (geom);

-- تعبئة الشبكات بدقة كل مصدر
TRUNCATE rain_cells;
INSERT INTO rain_cells (source, ix, iy, res, west, south, geom)
SELECT 'imerg_v07', ix-1, iy-1, 0.1, 34.4, 15.0,
       ST_SetSRID(ST_MakePoint(34.4 + (ix-0.5)*0.1, 15.0 + (iy-0.5)*0.1), 4326)
FROM generate_series(1, 212) ix, generate_series(1, 173) iy;

INSERT INTO rain_cells (source, ix, iy, res, west, south, geom)
SELECT 'chirps_v3', ix-1, iy-1, 0.05, 34.4, 15.0,
       ST_SetSRID(ST_MakePoint(34.4 + (ix-0.5)*0.05, 15.0 + (iy-0.5)*0.05), 4326)
FROM generate_series(1, 424) ix, generate_series(1, 346) iy;

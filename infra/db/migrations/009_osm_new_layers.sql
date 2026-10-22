-- فهارس وأطوال + وظائف MVT للطبقات الثماني الجديدة + الكتالوج
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['tracks','fords','ridgelines','springs','caves','helipads','passes','dunes'] LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I_geom_idx ON %I USING gist (geom);', t, t);
  END LOOP;
  EXECUTE 'ALTER TABLE tracks ADD COLUMN IF NOT EXISTS length_km double precision';
  EXECUTE 'UPDATE tracks SET length_km = ST_Length(geom::geography)/1000.0 WHERE length_km IS NULL';
  EXECUTE 'CREATE INDEX IF NOT EXISTS tracks_len_idx ON tracks (length_km)';
  EXECUTE 'ALTER TABLE ridgelines ADD COLUMN IF NOT EXISTS length_km double precision';
  EXECUTE 'UPDATE ridgelines SET length_km = ST_Length(geom::geography)/1000.0 WHERE length_km IS NULL';
END $$;

-- الدروب: ترشيح بالطول حسب التكبير + تبسيط
CREATE OR REPLACE FUNCTION mvt_tracks(z integer, x integer, y integer)
RETURNS bytea AS $func$
DECLARE mvt bytea; bbox geometry := ST_TileEnvelope(z, x, y);
  thr float := CASE WHEN z <= 7 THEN 8 WHEN z = 8 THEN 4 WHEN z = 9 THEN 1.5
                    WHEN z = 10 THEN 0.6 ELSE 0 END;
  simpl float := CASE WHEN z < 9 THEN 1.6*0.703/power(2,z) WHEN z < 12 THEN 0.703/power(2,z)*0.9 ELSE 0 END;
BEGIN
  IF z < 7 THEN RETURN NULL; END IF;
  SELECT ST_AsMVT(q, 'tracks', 4096, 'g') INTO mvt FROM (
    SELECT ST_AsMVTGeom(ST_Transform(ST_Intersection(ST_Simplify(t.geom, simpl), ST_Transform(bbox,4326)),3857),
           ST_Transform(bbox,3857),4096,256,true) AS g,
           t.name, t.quality, t.surface, t.sandy, t.abandoned
    FROM tracks t
    WHERE geom && ST_Transform(bbox,4326) AND t.length_km >= thr
      AND NOT ST_IsEmpty(ST_Simplify(t.geom, simpl))
  ) q WHERE q.g IS NOT NULL;
  RETURN mvt;
END; $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

-- نقاط العبور (مقاطع قصيرة)
CREATE OR REPLACE FUNCTION mvt_fords(z integer, x integer, y integer)
RETURNS bytea AS $func$
DECLARE mvt bytea; bbox geometry := ST_TileEnvelope(z, x, y);
BEGIN
  IF z < 8 THEN RETURN NULL; END IF;
  SELECT ST_AsMVT(q, 'fords', 4096, 'g') INTO mvt FROM (
    SELECT ST_AsMVTGeom(ST_Transform(ST_Intersection(f.geom, ST_Transform(bbox,4326)),3857),
           ST_Transform(bbox,3857),4096,256,true) AS g, f.name
    FROM fords f WHERE geom && ST_Transform(bbox,4326)
  ) q WHERE q.g IS NOT NULL;
  RETURN mvt;
END; $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

-- التقاسي
CREATE OR REPLACE FUNCTION mvt_ridgelines(z integer, x integer, y integer)
RETURNS bytea AS $func$
DECLARE mvt bytea; bbox geometry := ST_TileEnvelope(z, x, y);
  thr float := CASE WHEN z <= 8 THEN 4 WHEN z = 9 THEN 1.5 ELSE 0 END;
  simpl float := CASE WHEN z < 10 THEN 1.6*0.703/power(2,z) ELSE 0 END;
BEGIN
  IF z < 8 THEN RETURN NULL; END IF;
  SELECT ST_AsMVT(q, 'ridgelines', 4096, 'g') INTO mvt FROM (
    SELECT ST_AsMVTGeom(ST_Transform(ST_Intersection(ST_Simplify(r.geom, simpl), ST_Transform(bbox,4326)),3857),
           ST_Transform(bbox,3857),4096,256,true) AS g, r.name
    FROM ridgelines r
    WHERE geom && ST_Transform(bbox,4326) AND r.length_km >= thr
  ) q WHERE q.g IS NOT NULL;
  RETURN mvt;
END; $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

-- نقاط (ينابيع/كهوف/مهابط/عقبات) — قالب واحد
DO $$
DECLARE rec record;
BEGIN
  FOR rec IN
    SELECT * FROM (VALUES
      ('springs','الينابيع والمياه',11),('caves','الكهوف والمبيت',11),
      ('helipads','المهابط',10),('passes','العقبات',10)
    ) v(key, n, mz)
  LOOP
    EXECUTE format($f$
      CREATE OR REPLACE FUNCTION mvt_%I(z integer, x integer, y integer)
      RETURNS bytea AS $func$
      DECLARE mvt bytea; bbox geometry := ST_TileEnvelope(z, x, y);
      BEGIN
        IF z < %s THEN RETURN NULL; END IF;
        SELECT ST_AsMVT(q, %L, 4096, 'g') INTO mvt FROM (
          SELECT ST_AsMVTGeom(ST_Transform(t.geom,3857), ST_Transform(bbox,3857),4096,256,true) AS g,
                 t.name, t.kind
          FROM %I t WHERE geom && ST_Transform(bbox,4326)
        ) q WHERE q.g IS NOT NULL;
        RETURN mvt;
      END; $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE
    $f$, rec.key, rec.mz, rec.key, rec.key);
  END LOOP;
END $$;

-- الكثبان
CREATE OR REPLACE FUNCTION mvt_dunes(z integer, x integer, y integer)
RETURNS bytea AS $func$
DECLARE mvt bytea; bbox geometry := ST_TileEnvelope(z, x, y);
  simpl float := CASE WHEN z < 10 THEN 1.4*0.703/power(2,z) ELSE 0 END;
BEGIN
  IF z < 8 THEN RETURN NULL; END IF;
  SELECT ST_AsMVT(q, 'dunes', 4096, 'g') INTO mvt FROM (
    SELECT ST_AsMVTGeom(ST_Transform(ST_Intersection(ST_SimplifyPreserveTopology(d.geom, simpl), ST_Transform(bbox,4326)),3857),
           ST_Transform(bbox,3857),4096,256,true) AS g, d.name
    FROM dunes d WHERE geom && ST_Transform(bbox,4326)
  ) q WHERE q.g IS NOT NULL;
  RETURN mvt;
END; $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

-- الكتالوج
INSERT INTO layers_meta (key, name_ar, name_en, group_ar, geom_type, minzoom, ord, style, enabled) VALUES
  ('tracks', 'دروب الصحراء (بجودتها)', 'Desert Tracks', 'التنقل الصحراوي', 'line', 7, 80,
   '{"quality_colors": {1: "#2e7d32", 2: "#7cb342", 3: "#f9a825", 4: "#ef6c00", 5: "#c62828"}}', true),
  ('fords', 'نقاط عبور الفياض', 'Fords', 'التنقل الصحراوي', 'line', 8, 81,
   '{"color": "#0284c7", "dashed": true}', true),
  ('passes', 'العقبات والممرات', 'Mountain Passes', 'التنقل الصحراوي', 'point', 10, 82,
   '{"marker": "pass", "color": "#7c3aed"}', true),
  ('helipads', 'مهابط الهليكوبتر', 'Helipads', 'التنقل الصحراوي', 'point', 10, 83,
   '{"marker": "helipad", "color": "#475569"}', true),
  ('dunes', 'الكثبان الرملية (عروق)', 'Sand Dunes (Ergs)', 'كنوز الصحراء', 'polygon', 8, 84,
   '{"fill": "#e8d5a3", "fill_opacity": 0.45, "outline": "#d4b96a"}', true),
  ('ridgelines', 'خطوط التقاسي', 'Ridgelines', 'كنوز الصحراء', 'line', 8, 85,
   '{"color": "#8d6e63", "width": 1.1}', true),
  ('springs', 'العيون ومياه الشرب', 'Springs & Water', 'كنوز الصحراء', 'point', 11, 86,
   '{"marker": "spring", "color": "#0ea5e9", "label": true}', true),
  ('caves', 'الكهوف والمبيت', 'Caves & Huts', 'كنوز الصحراء', 'point', 11, 87,
   '{"marker": "cave", "color": "#57534e"}', true)
ON CONFLICT (key) DO NOTHING;

-- إضافة للبحث
INSERT INTO places_search (name, kind, source, src_id, geom)
  SELECT s.name, s.kind, 'springs', s.gid, s.geom FROM springs s WHERE s.name IS NOT NULL
  UNION ALL
  SELECT c.name, 'كهف/مبيت', 'caves', c.gid, c.geom FROM caves c WHERE c.name IS NOT NULL
  UNION ALL
  SELECT p.name, 'عقبة', 'passes', p.gid, p.geom FROM passes p WHERE p.name IS NOT NULL;

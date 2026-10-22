-- إكمال الكتالوج + ترشيح التجمعات حسب التكبير + تجديد وظائف الطبقات الجديدة

INSERT INTO layers_meta (key, name_ar, name_en, group_ar, geom_type, minzoom, ord, style) VALUES
  ('telecom_offices', 'مكاتب الاتصالات', 'Telecom Offices', 'النقاط الحيوية', 'point', 12, 34,
   '{"marker": "office", "color": "#7a7a7a"}'),
  ('education', 'الجامعات والكليات', 'Education', 'المعالم', 'point', 12, 44,
   '{"marker": "education", "color": "#5b6db8"}'),
  ('military_areas', 'مناطق عسكرية', 'Military Areas', 'المعالم', 'polygon', 11, 45,
   '{"fill": "#9a9a9a", "fill_opacity": 0.2, "dashed": true}'),
  ('cemeteries', 'المقابر', 'Cemeteries', 'المعالم', 'polygon', 12, 46,
   '{"fill": "#b0a58f", "fill_opacity": 0.35}'),
  ('utilities', 'منشآت المرافق', 'Utilities', 'النقاط الحيوية', 'point', 13, 35,
   '{"marker": "utility", "color": "#8a6d3b"}'),
  ('industrial_areas', 'مناطق صناعية', 'Industrial Areas', 'المعالم', 'polygon', 12, 47,
   '{"fill": "#a8a8a8", "fill_opacity": 0.25}')
ON CONFLICT (key) DO NOTHING;

-- تجديد وظائف MVT للطبقات الست الجديدة فقط
DO $$
DECLARE rec record;
BEGIN
  FOR rec IN SELECT key, geom_type, minzoom FROM layers_meta
             WHERE key IN ('telecom_offices','education','military_areas','cemeteries','utilities','industrial_areas')
  LOOP
    EXECUTE format($f$
      CREATE OR REPLACE FUNCTION %I(z integer, x integer, y integer)
      RETURNS bytea AS $func$
      DECLARE
        mvt bytea;
        bbox geometry := ST_TileEnvelope(z, x, y);
      BEGIN
        IF z < %s THEN RETURN NULL; END IF;
        SELECT ST_AsMVT(q, %L, 4096, 'g') INTO mvt
        FROM (
          SELECT ST_AsMVTGeom(ST_Transform(t.geom, 3857),
                   ST_Transform(bbox, 3857), 4096, 256, true) AS g,
                 (to_jsonb(t.*) - 'geom' - 'gid') AS props
          FROM %I t
          WHERE geom && ST_Transform(bbox, 4326) AND NOT ST_IsEmpty(geom)
        ) q WHERE q.g IS NOT NULL;
        RETURN mvt;
      END;
      $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE
    $f$, format('mvt_%s', rec.key), rec.minzoom, rec.key, rec.key);
  END LOOP;
END $$;

-- ترشيح التجمعات حسب التكبير: مدن فقط عند z7-8، +قرى عند z9-10، الكل من z11
CREATE OR REPLACE FUNCTION mvt_settlements(z integer, x integer, y integer)
RETURNS bytea AS $func$
DECLARE
  mvt bytea;
  bbox geometry := ST_TileEnvelope(z, x, y);
BEGIN
  IF z < 7 THEN RETURN NULL; END IF;
  SELECT ST_AsMVT(q, 'settlements', 4096, 'g') INTO mvt
  FROM (
    SELECT ST_AsMVTGeom(ST_Transform(t.geom, 3857),
             ST_Transform(bbox, 3857), 4096, 256, true) AS g,
           (to_jsonb(t.*) - 'geom' - 'gid') AS props
    FROM settlements t
    WHERE geom && ST_Transform(bbox, 4326)
      AND CASE
            WHEN z < 8  THEN kind = 'مدينة'
            WHEN z < 10 THEN kind IN ('مدينة','قرية')
            ELSE true
          END
  ) q WHERE q.g IS NOT NULL;
  RETURN mvt;
END;
$func$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

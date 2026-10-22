-- إعادة توليد وظائف MVT بخصائص مسطّحة (أعمدة显式ة بدل jsonb متداخل)
DO $$
DECLARE
  rec record;
  cols text;
  fn text;
  simpl text;
BEGIN
  FOR rec IN
    SELECT m.key, m.geom_type, m.minzoom,
           (SELECT string_agg(format('t.%I', c.column_name), ', ')
              FROM information_schema.columns c
             WHERE c.table_name = m.key AND c.column_name NOT IN ('geom','gid')) AS collist
    FROM layers_meta m
    WHERE m.key <> 'roads'
  LOOP
    fn := format('mvt_%s', rec.key);
    cols := COALESCE(rec.collist, 'NULL::text AS name');

    CASE rec.geom_type
      WHEN 'line' THEN
        simpl := format('ST_Simplify(t.geom, CASE WHEN z < 12 THEN 0.703 / power(2, z) * 0.9 ELSE 0 END)');
      WHEN 'polygon' THEN
        simpl := format('ST_SimplifyPreserveTopology(t.geom, CASE WHEN z < 12 THEN 0.703 / power(2, z) * 0.7 ELSE 0 END)');
      ELSE
        simpl := 't.geom';
    END CASE;

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
          SELECT ST_AsMVTGeom(
                   ST_Transform(ST_Intersection(%s, ST_Transform(bbox, 4326)), 3857),
                   ST_Transform(bbox, 3857), 4096, 256, true) AS g,
                 %s
          FROM %I t
          WHERE geom && ST_Transform(bbox, 4326) AND NOT ST_IsEmpty(%s)
        ) q WHERE q.g IS NOT NULL;
        RETURN mvt;
      END;
      $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE
    $f$, fn, rec.minzoom, rec.key,
         replace(simpl, 't.geom', 't.geom'), cols, rec.key,
         replace(simpl, 't.geom', 't.geom'));
  END LOOP;
END $$;

-- استثناء خاص: التجمعات مع ترشيح حسب التكبير تبقى كما في 004 (أعمدتها显式ة أصلاً)
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
           t.name, t.kind, t.osm_id
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

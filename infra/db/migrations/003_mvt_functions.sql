-- وظائف MVT لكل طبقة (Martin function sources) مع تبسيط هندسي حسب التكبير.
-- التبسيط ضروري لطبقة waterways (322 ألف خط): z7 يعرض بمقاومة ~0.005° (~500م).
DO $$
DECLARE
  rec record;
  fn text;
  simpl text;
  geom_expr text;
  props text;
BEGIN
  FOR rec IN SELECT key, geom_type, minzoom FROM layers_meta WHERE key <> 'roads' LOOP
    fn := format('mvt_%s', rec.key);
    CASE rec.geom_type
      WHEN 'line' THEN
        simpl := format(
          'ST_Simplify(geom, CASE WHEN %1$s < 12 THEN 0.703 / power(2, %1$s) * 0.9 ELSE 0 END)',
          'z');
      WHEN 'polygon' THEN
        simpl := format(
          'ST_SimplifyPreserveTopology(geom, CASE WHEN %1$s < 12 THEN 0.703 / power(2, %1$s) * 0.7 ELSE 0 END)',
          'z');
      ELSE
        simpl := 'geom';
    END CASE;

    EXECUTE format($f$
      CREATE OR REPLACE FUNCTION %I(z integer, x integer, y integer)
      RETURNS bytea AS $func$
      DECLARE
        mvt bytea;
        bbox geometry := ST_TileEnvelope(z, x, y);
        clip_geom geometry;
      BEGIN
        IF z < %s THEN RETURN NULL; END IF;
        SELECT ST_AsMVT(q, %L, 4096, 'g') INTO mvt
        FROM (
          SELECT ST_AsMVTGeom(
                   ST_Transform(ST_Intersection(%s, ST_Transform(bbox, 4326)), 3857),
                   ST_Transform(bbox, 3857), 4096, 256, true) AS g,
                 (to_jsonb(t.*) - 'geom' - 'gid') AS props
          FROM %I t
          WHERE geom && ST_Transform(bbox, 4326) AND NOT ST_IsEmpty(%s)
        ) q WHERE q.g IS NOT NULL;
        RETURN mvt;
      END;
      $func$ LANGUAGE plpgsql STABLE PARALLEL SAFE
    $f$, fn, rec.minzoom, rec.key,
         replace(simpl, 'geom', 't.geom'), rec.key,
         replace(simpl, 'geom', 't.geom'));
  END LOOP;
END $$;

-- المواد المجمّلة لكل مصدر + دوال التحديث + منطق الوسم

-- تفريغ راستر يومي إلى rain_values (يستدعى من الـ ETL بعد إدخال كل يوم)
CREATE OR REPLACE FUNCTION rain_ingest_values(p_day date, p_product text, p_source text)
RETURNS int AS $f$
DECLARE
  n int;
BEGIN
  DELETE FROM rain_values WHERE day = p_day AND source = p_source;
  INSERT INTO rain_values (day, source, iy, ix, val)
  SELECT p_day, p_source, u2.iy - 1, u1.ix - 1, u1.val
  FROM rain_daily rd,
       LATERAL ST_DumpValues(rd.rast, 1) dv,
       LATERAL unnest(dv.val) WITH ORDINALITY AS u2(rowvals, iy),
       LATERAL unnest(u2.rowvals) WITH ORDINALITY AS u1(val, ix)
  WHERE rd.day = p_day AND rd.product = p_product;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$f$ LANGUAGE plpgsql;

-- منطق الوسم: نافذة السنة الجارية إن بدأت وإلا آخر وسم مكتمل (السنة الماضية)
CREATE OR REPLACE FUNCTION wasm_window(today date, start_md text, length_days int)
RETURNS TABLE(win_start date, win_end date, win_year int, ongoing boolean) AS $f$
DECLARE
  sy int := EXTRACT(year FROM today)::int;
  s date := make_date(sy, split_part(start_md,'-',1)::int, split_part(start_md,'-',2)::int);
  e date := s + (length_days - 1);
BEGIN
  IF today >= s THEN
    -- وسم هذه السنة بدأ: جارٍ إن لم يكتمل بعد
    RETURN QUERY SELECT s, least(e, today), sy, (today <= e);
  ELSE
    -- لم يبدأ بعد: آخر وسم مكتمل = سنة ماضية
    s := make_date(sy-1, split_part(start_md,'-',1)::int, split_part(start_md,'-',2)::int);
    RETURN QUERY SELECT s, s + (length_days - 1), sy-1, false;
  END IF;
END;
$f$ LANGUAGE plpgsql STABLE;

-- مواد مجمّلة لكل مصدر (تتحدث ليلياً وبعد كل استيعاب)
DO $$
DECLARE src text;
BEGIN
  FOREACH src IN ARRAY ARRAY['imerg_v07','chirps_v3'] LOOP
    EXECUTE format($m$
      CREATE MATERIALIZED VIEW IF NOT EXISTS mv_rain_cell_%1$s AS
      WITH md AS (SELECT max(day) md FROM rain_values WHERE source = '%1$s'),
      w AS (SELECT ww.* FROM app_settings,
            LATERAL wasm_window((SELECT md FROM md),
                 value->>'start', (value->>'length_days')::int) ww
            WHERE key = 'wasm'),
      bounds AS (
        SELECT (SELECT md FROM md) - 10  AS d10, (SELECT md FROM md) - 20 AS d20,
               (SELECT md FROM md) - 40  AS d40, (SELECT md FROM md) - 90 AS d90,
               (SELECT md FROM md) - 365 AS d365,
               (SELECT win_start FROM w) AS ws, (SELECT win_end FROM w) AS we,
               (SELECT win_year FROM w) AS wy, (SELECT ongoing FROM w) AS wgo
      )
      SELECT c.source, c.ix, c.iy, c.geom,
             coalesce(v10.s, 0)::real  AS sum_10d,
             coalesce(v20.s, 0)::real  AS sum_20d,
             coalesce(v40.s, 0)::real  AS sum_40d,
             coalesce(v90.s, 0)::real  AS sum_90d,
             coalesce(v365.s, 0)::real AS sum_365d,
             coalesce(vw.s, 0)::real   AS wasm_sum,
             b.wy AS wasm_year, b.wgo AS wasm_ongoing,
             lr.last_rain_day
      FROM rain_cells c
      CROSS JOIN bounds b
      LEFT JOIN LATERAL (SELECT sum(val) s FROM rain_values v
          WHERE v.source=c.source AND v.ix=c.ix AND v.iy=c.iy AND v.day >  b.d10) v10 ON true
      LEFT JOIN LATERAL (SELECT sum(val) s FROM rain_values v
          WHERE v.source=c.source AND v.ix=c.ix AND v.iy=c.iy AND v.day >  b.d20) v20 ON true
      LEFT JOIN LATERAL (SELECT sum(val) s FROM rain_values v
          WHERE v.source=c.source AND v.ix=c.ix AND v.iy=c.iy AND v.day >  b.d40) v40 ON true
      LEFT JOIN LATERAL (SELECT sum(val) s FROM rain_values v
          WHERE v.source=c.source AND v.ix=c.ix AND v.iy=c.iy AND v.day >  b.d90) v90 ON true
      LEFT JOIN LATERAL (SELECT sum(val) s FROM rain_values v
          WHERE v.source=c.source AND v.ix=c.ix AND v.iy=c.iy AND v.day >  b.d365) v365 ON true
      LEFT JOIN LATERAL (SELECT sum(val) s FROM rain_values v
          WHERE v.source=c.source AND v.ix=c.ix AND v.iy=c.iy
            AND v.day >= b.ws AND v.day <= b.we) vw ON true
      LEFT JOIN LATERAL (SELECT max(day) last_rain_day FROM rain_values v
          WHERE v.source=c.source AND v.ix=c.ix AND v.iy=c.iy AND v.val >= 0.1) lr ON true
      WHERE c.source = '%1$s'
      $m$, src);
    EXECUTE format('CREATE UNIQUE INDEX IF NOT EXISTS mv_rc_%1$s_uq ON mv_rain_cell_%1$s (ix, iy)', src);
    EXECUTE format('CREATE INDEX IF NOT EXISTS mv_rc_%1$s_geom ON mv_rain_cell_%1$s USING gist (geom)', src);
  END LOOP;
END $$;

-- تحديث المواد (CONCURRENTLY للتوفر أثناء القراءة)
CREATE OR REPLACE FUNCTION refresh_rain_mvs() RETURNS void AS $f$
DECLARE src text;
BEGIN
  FOREACH src IN ARRAY ARRAY['imerg_v07','chirps_v3'] LOOP
    EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY mv_rain_cell_%s', src);
  END LOOP;
END;
$f$ LANGUAGE plpgsql;

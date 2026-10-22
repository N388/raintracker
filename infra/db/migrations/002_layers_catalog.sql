-- فهارس جغرافية لكل طبقات الصحراء + كتالوج + جدول البحث
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'waterways','settlements','scrub','wetlands','peaks','fuel_stations','wells',
    'antennas','water_bodies','cairns','viewpoints','farmland','protected_areas',
    'dams','craters','telecom_offices','education','slopes','archaeology',
    'military_areas','cemeteries','utilities','industrial_areas'
  ] LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I_geom_idx ON %I USING gist (geom);', t, t);
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I_name_idx ON %I (name);', t, t);
  END LOOP;
END $$;

-- كتالوج الطبقات (يعرض في الواجهة ويغذي Martin)
INSERT INTO layers_meta (key, name_ar, name_en, group_ar, geom_type, minzoom, ord, style) VALUES
  ('waterways', 'الأودية والمجاري', 'Waterways', 'المياه', 'line', 7, 10,
   '{"color": "#4a90c2", "width": 1.2, "waterway_class_colors": {"فيضة": "#1f78b4", "وادي": "#4a90c2", "شعب": "#7b68a6", "روضة": "#3c9a5f", "سبخة": "#8a6d3b", "أخرى": "#8bb8d8"}}'),
  ('water_bodies', 'المياه السطحية', 'Water Bodies', 'المياه', 'polygon', 9, 11,
   '{"fill": "#9ec9e8", "fill_opacity": 0.55, "outline": "#5a9fd4"}'),
  ('wetlands', 'الأراضي الرطبة (سباخ)', 'Wetlands', 'المياه', 'polygon', 9, 12,
   '{"fill": "#7fbf9a", "fill_opacity": 0.4, "outline": "#4f9a70"}'),
  ('dams', 'السدود', 'Dams', 'المياه', 'line', 11, 13,
   '{"color": "#8a6d3b", "width": 2.0}'),
  ('peaks', 'القمم الجبلية', 'Peaks', 'التضاريس', 'point', 9, 20,
   '{"marker": "mountain", "color": "#6b4f3a", "label": true}'),
  ('craters', 'الفوهات البركانية', 'Craters', 'التضاريس', 'point', 10, 21,
   '{"marker": "crater", "color": "#8b5a2b"}'),
  ('slopes', 'الانحدارات', 'Slopes', 'التضاريس', 'polygon', 11, 22,
   '{"fill": "#c9b895", "fill_opacity": 0.35}'),
  ('scrub', 'الشجيرات', 'Scrub', 'التضاريس', 'polygon', 9, 23,
   '{"fill": "#b7c48a", "fill_opacity": 0.3, "outline": "#96a56a"}'),
  ('wells', 'آبار المياه', 'Water Wells', 'النقاط الحيوية', 'point', 10, 30,
   '{"marker": "well", "color": "#1f78b4", "label": true}'),
  ('cairns', 'علامات الدلالة', 'Cairns', 'النقاط الحيوية', 'point', 12, 31,
   '{"marker": "cairn", "color": "#6b4f3a"}'),
  ('fuel_stations', 'محطات الوقود', 'Fuel Stations', 'النقاط الحيوية', 'point', 10, 32,
   '{"marker": "fuel", "color": "#d9534f", "label": true}'),
  ('antennas', 'أبراج الاتصالات', 'Antennas', 'النقاط الحيوية', 'point', 11, 33,
   '{"marker": "antenna", "color": "#7a7a7a"}'),
  ('viewpoints', 'نقاط المنظر', 'Viewpoints', 'المعالم', 'point', 11, 40,
   '{"marker": "viewpoint", "color": "#e8a13c"}'),
  ('archaeology', 'المواقع الأثرية', 'Archaeological Sites', 'المعالم', 'point', 12, 41,
   '{"marker": "ruins", "color": "#a0522d"}'),
  ('protected_areas', 'المناطق المحمية', 'Protected Areas', 'المعالم', 'polygon', 9, 42,
   '{"fill": "#5cb85c", "fill_opacity": 0.15, "outline": "#3d8b3d", "dashed": true}'),
  ('farmland', 'الأراضي الزراعية', 'Farmland', 'المعالم', 'polygon', 11, 43,
   '{"fill": "#e8d78a", "fill_opacity": 0.3}'),
  ('settlements', 'التجمعات السكانية', 'Settlements', 'الأماكن', 'point', 7, 50,
   '{"label": true, "label_field": "name", "label_sizes": {"مدينة": 15, "قرية": 12, "هجرة": 11, "تجمع": 10}}'),
  ('roads', 'الطرق', 'Roads', 'الطرق', 'line', 8, 60,
   '{"color": "#d8cfbf", "width": 1.0, "casing": "#b0a48e"}')
ON CONFLICT (key) DO NOTHING;

-- جدول البحث الموحّد من الطبقات المستوردة
TRUNCATE places_search;
INSERT INTO places_search (name, kind, source, src_id, geom)
  SELECT s.name, s.kind, 'settlements', s.gid, s.geom
    FROM settlements s WHERE s.name IS NOT NULL
  UNION ALL
  SELECT p.name, 'جبل', 'peaks', p.gid, p.geom
    FROM peaks p WHERE p.name IS NOT NULL
  UNION ALL
  SELECT w.name, 'بئر ماء', 'wells', w.gid, w.geom
    FROM wells w WHERE w.name IS NOT NULL
  UNION ALL
  SELECT w.name,
         CASE w.class WHEN 'وادي' THEN 'واد' WHEN 'فيضة' THEN 'فيضة'
                      WHEN 'روضة' THEN 'روضة' WHEN 'شعب' THEN 'شعب' ELSE 'مجرى ماء' END,
         'waterways', w.gid, ST_LineInterpolatePoint(w.geom::geometry, 0.5)
    FROM waterways w WHERE w.name IS NOT NULL
  UNION ALL
  SELECT c.name, 'علامة دلالة', 'cairns', c.gid, c.geom
    FROM cairns c WHERE c.name IS NOT NULL
  UNION ALL
  SELECT v.name, 'نقطة منظر', 'viewpoints', v.gid, v.geom
    FROM viewpoints v WHERE v.name IS NOT NULL;

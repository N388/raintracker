-- طبقات المرجع من خريطة الأساس (OSM/PMTiles): طرق، حدود إدارية، أسماء أماكن
INSERT INTO layers_meta (key, name_ar, name_en, group_ar, geom_type, minzoom, ord, style, enabled) VALUES
  ('ref_roads', 'الطرق', 'Roads', 'المرجع', 'line', 6, 70,
   '{"source_layer": "transportation", "color": "#d9cfbe", "width_zoom": true}', true),
  ('ref_boundaries', 'الحدود الإدارية', 'Boundaries', 'المرجع', 'line', 5, 71,
   '{"source_layer": "boundary", "color": "#b09a78", "dashed": true}', true),
  ('ref_places', 'أسماء الأماكن', 'Place Names', 'المرجع', 'point', 5, 72,
   '{"source_layer": "place", "text_field_ar": true}', true)
ON CONFLICT (key) DO NOTHING;

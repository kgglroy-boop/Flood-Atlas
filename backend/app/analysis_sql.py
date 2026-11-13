"""Fixed SQL fragments. Only bound values vary; inputs are never supplied by HTTP."""
INPUTS_SQL = """
WITH extent_parts AS (
 SELECT geom FROM flood.flood_extents WHERE scenario_id=%(scenario_id)s AND time_min=%(time_min)s
), selected_buildings AS (
 SELECT building_id,name,usage,geom FROM flood.buildings WHERE dataset_id=%(dataset_id)s
), selected_roads AS (
 SELECT road_id,geom FROM flood.roads WHERE dataset_id=%(dataset_id)s
)
"""
WET_SQL = ", wet AS (SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM extent_parts)\n"
SUMMARY_SQL = """
SELECT ST_Area(w.geom) AS flooded_area_m2,
 (SELECT count(DISTINCT b.building_id) FROM selected_buildings b
  WHERE ST_Intersects(b.geom,w.geom)) AS affected_buildings,
 COALESCE((SELECT sum(ST_Length(ST_CollectionExtract(ST_Intersection(r.geom,w.geom),2)))
  FROM selected_roads r WHERE ST_Intersects(r.geom,w.geom)),0.0) AS flooded_road_length_m
FROM wet w
"""
BUILDINGS_SQL = """
SELECT b.building_id,b.name,b.usage,ST_Intersects(b.geom,w.geom) AS affected,
 ST_AsGeoJSON(ST_Transform(b.geom,4326),9)::jsonb AS geometry,
 count(*) OVER () AS total_buildings
FROM selected_buildings b CROSS JOIN wet w
ORDER BY b.building_id LIMIT %(limit)s
"""

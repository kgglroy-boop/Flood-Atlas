-- Explicit migration, invoked transactionally by the teaching data CLI.
-- Never mounted as an initdb script: existing named volumes must work too.
CREATE SCHEMA IF NOT EXISTS flood;

CREATE TABLE IF NOT EXISTS flood.dataset_info (
    dataset_id text PRIMARY KEY CHECK (dataset_id = 'teaching-v1'),
    generation_id text NOT NULL CHECK (generation_id ~ '^[0-9a-f]{20}$'),
    model_type text NOT NULL CHECK (model_type = 'synthetic_demo'),
    contract_version text NOT NULL CHECK (contract_version = '1.0'),
    analysis_srid integer NOT NULL CHECK (analysis_srid = 32650)
);
CREATE TABLE IF NOT EXISTS flood.study_area (
    area_id text PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES flood.dataset_info(dataset_id),
    name text NOT NULL,
    geom public.geometry(MultiPolygon,32650) NOT NULL,
    CONSTRAINT study_area_valid CHECK (public.ST_IsValid(geom) AND NOT public.ST_IsEmpty(geom))
);
CREATE TABLE IF NOT EXISTS flood.scenarios (
    scenario_id text PRIMARY KEY CHECK (scenario_id IN ('S01','S02')),
    dataset_id text NOT NULL REFERENCES flood.dataset_info(dataset_id),
    name text NOT NULL,
    model_type text NOT NULL CHECK (model_type = 'synthetic_demo')
);
CREATE TABLE IF NOT EXISTS flood.scenario_steps (
    scenario_id text NOT NULL REFERENCES flood.scenarios(scenario_id),
    time_min integer NOT NULL CHECK (time_min IN (0,30,60)),
    step_code text NOT NULL,
    raster_relative_path text NOT NULL CHECK (raster_relative_path !~ '(^/|\.\.|:|\\)'),
    generation_id text NOT NULL CHECK (generation_id ~ '^[0-9a-f]{20}$'),
    PRIMARY KEY (scenario_id,time_min),
    CONSTRAINT step_code_matches_time CHECK (step_code = 'T' || lpad(time_min::text,2,'0'))
);
CREATE TABLE IF NOT EXISTS flood.buildings (
    building_id text PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES flood.dataset_info(dataset_id),
    name text NOT NULL,
    usage text NOT NULL CHECK (usage = 'demo'),
    geom public.geometry(Polygon,32650) NOT NULL,
    CONSTRAINT buildings_valid CHECK (public.ST_IsValid(geom) AND NOT public.ST_IsEmpty(geom))
);
CREATE TABLE IF NOT EXISTS flood.roads (
    road_id text PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES flood.dataset_info(dataset_id),
    name text NOT NULL,
    direction text NOT NULL CHECK (direction IN ('vertical','horizontal')),
    geom public.geometry(LineString,32650) NOT NULL,
    CONSTRAINT roads_valid CHECK (public.ST_IsValid(geom) AND NOT public.ST_IsEmpty(geom))
);
CREATE TABLE IF NOT EXISTS flood.flood_extents (
    scenario_id text NOT NULL,
    time_min integer NOT NULL,
    wet_pixel_count integer NOT NULL CHECK (wet_pixel_count BETWEEN 0 AND 80000),
    area_m2 double precision NOT NULL CHECK (area_m2 BETWEEN 0 AND 2000000),
    threshold_m double precision NOT NULL CHECK (threshold_m = 0.1),
    geom public.geometry(MultiPolygon,32650) NOT NULL,
    PRIMARY KEY (scenario_id,time_min),
    FOREIGN KEY (scenario_id,time_min) REFERENCES flood.scenario_steps(scenario_id,time_min),
    CONSTRAINT flood_extents_valid CHECK (public.ST_IsValid(geom)),
    CONSTRAINT flood_extents_area CHECK (area_m2 = wet_pixel_count * 25
        AND abs(public.ST_Area(geom) - area_m2) <= 0.01
        AND (public.ST_IsEmpty(geom) = (wet_pixel_count = 0)))
);
CREATE INDEX IF NOT EXISTS study_area_geom_gist ON flood.study_area USING gist(geom);
CREATE INDEX IF NOT EXISTS buildings_geom_gist ON flood.buildings USING gist(geom);
CREATE INDEX IF NOT EXISTS roads_geom_gist ON flood.roads USING gist(geom);
CREATE INDEX IF NOT EXISTS flood_extents_geom_gist ON flood.flood_extents USING gist(geom);

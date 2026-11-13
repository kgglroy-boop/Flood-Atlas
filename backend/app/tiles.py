"""Static engineering demonstration of real PostGIS MVT, independent of flood time."""
import logging
import re
import psycopg
from fastapi import APIRouter,HTTPException,Request,Response
from app.database import open_database
from app.scenarios import read_catalog_snapshot,ScenarioCatalogUnavailable
from app.analysis_store import _invalid_geometry

router=APIRouter(prefix='/api/v1/tiles',tags=['engineering vector tiles'])
logger=logging.getLogger('urban_flood.tiles')
class TileDataUnavailable(ValueError):pass

TILE_SQL="""WITH bounds AS(SELECT ST_TileEnvelope(%(z)s,%(x)s,%(y)s) box,
 ST_TileEnvelope(%(z)s,%(x)s,%(y)s,margin=>64.0/4096) buffered),
 source AS(SELECT building_id,name,usage,ST_Transform(geom,3857) geom
 FROM flood.buildings WHERE dataset_id=%(dataset_id)s),
 clipped AS(SELECT building_id,name,usage,ST_AsMVTGeom(s.geom,b.box,4096,64,true) geom
 FROM source s CROSS JOIN bounds b WHERE s.geom && b.buffered)
 SELECT COALESCE(ST_AsMVT(q,'buildings',4096,'geom'),''::bytea)
 FROM (SELECT building_id,name,usage,geom FROM clipped WHERE geom IS NOT NULL) q"""

def parse_tile(z,x,y,query):
    if query or any(re.fullmatch(r'[0-9]{1,6}',v) is None for v in (z,x,y)):
        raise HTTPException(422,'invalid tile coordinates')
    z,x,y=map(int,(z,x,y))
    if z>19 or x>=2**z or y>=2**z:raise HTTPException(422,'invalid tile coordinates')
    return z,x,y

def read_tile(connection,z,x,y):
    try:
        with connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            read_catalog_snapshot(connection)
            count,bad=connection.execute('SELECT count(*),bool_or('+_invalid_geometry('POLYGON')+
                ') FROM flood.buildings WHERE dataset_id=%s',('teaching-v1',)).fetchone()
            if count!=200 or bad:raise TileDataUnavailable('tile data unavailable')
            return bytes(connection.execute(TILE_SQL,dict(z=z,x=x,y=y,dataset_id='teaching-v1')).fetchone()[0])
    except (ScenarioCatalogUnavailable,psycopg.errors.UndefinedTable,psycopg.errors.UndefinedColumn,psycopg.errors.InvalidSchemaName):
        raise TileDataUnavailable('tile data unavailable') from None

@router.get('/buildings/{z}/{x}/{y}.pbf',response_class=Response,
 responses={200:{'content':{'application/vnd.mapbox-vector-tile':{}},'description':'真实建筑MVT；空瓦片可为空字节。'},422:{'description':'非法瓦片请求'},503:{'description':'数据或数据库不可用'}},
 description='独立教学工程演示；3857瓦片，extent4096/buffer64；不用于面积或长度分析。')
def buildings_tile(z:str,x:str,y:str,request:Request):
    z,x,y=parse_tile(z,x,y,list(request.query_params.multi_items()))
    try:
        with open_database() as connection:content=read_tile(connection,z,x,y)
        return Response(content,media_type='application/vnd.mapbox-vector-tile',headers={'Cache-Control':'no-store'})
    except TileDataUnavailable:
        logger.warning('Tile data validation failed');raise HTTPException(503,'tile data unavailable') from None
    except psycopg.Error:
        logger.warning('Tile database read failed');raise HTTPException(503,'database unavailable') from None

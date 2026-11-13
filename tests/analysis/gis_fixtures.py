from osgeo import ogr, osr


def write_micro_gpkg(path, srid=32650):
    ds=ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
    crs=osr.SpatialReference();crs.ImportFromEPSG(srid)
    specs={'study_area':(ogr.wkbPolygon,[('area_id',ogr.OFTString)]),
           'buildings':(ogr.wkbPolygon,[(k,ogr.OFTString) for k in ('building_id','name','usage')]),
           'roads':(ogr.wkbLineString,[('road_id',ogr.OFTString)]),
           'flood_extents':(ogr.wkbMultiPolygon,[('scenario_id',ogr.OFTString),('time_min',ogr.OFTInteger)])}
    layers={}
    for name,(shape,fields) in specs.items():
        layer=ds.CreateLayer(name,crs,shape)
        for key,kind in fields: layer.CreateField(ogr.FieldDefn(key,kind))
        layers[name]=layer
    def add(name,wkt,properties):
        geometry=ogr.CreateGeometryFromWkt(wkt)
        if not geometry.IsEmpty():
            # Coordinate translation independent from production generation.
            def shift(g):
                for i in range(g.GetPointCount()):
                    x,y,*_=g.GetPoint(i);g.SetPoint_2D(i,x+500000,y+3400000)
                for i in range(g.GetGeometryCount()):shift(g.GetGeometryRef(i))
            shift(geometry)
        feature=ogr.Feature(layers[name].GetLayerDefn());feature.SetGeometry(geometry)
        for key,value in properties.items():feature.SetField(key,value)
        assert layers[name].CreateFeature(feature)==0
    def rectangle(x0,y0,x1,y1):return f'POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))'
    add('study_area',rectangle(-10,-10,30,30),{'area_id':'A01'})
    for n,box in enumerate([(4,2,11,4),(15,2,17,4),(15,10,17,12),(20,20,22,22)],1):
        add('buildings',rectangle(*box),{'building_id':f'B{n:03}','name':f'教学{n}','usage':'demo'})
    for n,wkt in enumerate(['LINESTRING(-5 5,20 5)','LINESTRING(-5 0,20 0)','LINESTRING(15 10,20 15)'],1):
        add('roads',wkt,{'road_id':f'R{n}'})
    for scenario in ('S01','S02'):
        for minute in (0,30,60):
            wkts=['MULTIPOLYGON EMPTY'] if minute==0 else ['MULTIPOLYGON(((0 0,10 0,10 10,0 10,0 0)))','MULTIPOLYGON(((5 0,15 0,15 10,5 10,5 0)))','MULTIPOLYGON(((0 0,10 0,10 10,0 10,0 0)))']
            for wkt in wkts:add('flood_extents',wkt,{'scenario_id':scenario,'time_min':minute})
    ds=None

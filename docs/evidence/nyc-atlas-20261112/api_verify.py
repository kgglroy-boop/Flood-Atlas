import hashlib, json, math, os, time, urllib.error, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = Path.cwd()
out = root/"work/nyc-final-20261112"
base = os.environ.get("FLOOD_QA_URL","http://localhost:5173")
key = next((line.partition("=")[2].strip() for line in (root/".env").read_text(encoding="utf-8-sig").splitlines()
            if line.startswith("FLOOD_IMPORT_TOKEN=")), "")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
auth = {"Authorization":"Bearer "+key, "Origin":base}

def fetch(path, headers=None, data=None, method=None):
    with opener.open(urllib.request.Request(base+path, headers=headers or {}, data=data, method=method), timeout=45) as response:
        return response.read(), dict(response.headers)

def get(path, headers=None, data=None, method=None):
    return json.loads(fetch(path, headers, data, method)[0])

def multipart(fields):
    boundary = uuid.uuid4().hex
    parts = []
    for field, value in fields:
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"'
        if isinstance(value,Path):
            parts.append((head + f'; filename="{value.name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+value.read_bytes()+b"\r\n")
        else:
            parts.append((head+"\r\n\r\n").encode()+value.encode()+b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return auth|{"Content-Type":"multipart/form-data; boundary="+boundary}, b"".join(parts)

def code(path, headers=None, data=None, method=None):
    try:
        fetch(path,headers,data,method)
        return 200
    except urllib.error.HTTPError as error:
        return error.code

def wait(job, states):
    for _ in range(150):
        result=get("/api/v2/imports/"+job,auth)
        if result["status"]=="error":
            raise RuntimeError(result["message"])
        if result["status"] in states:
            return result
        time.sleep(.8)
    raise RuntimeError("import wait expired")

catalog=get("/api/v2/cases")
case=next(item for item in catalog["cases"] if item["id"]==catalog["default"]=="nyc-ida")
v2=f'/api/v2/cases/{case["id"]}/{case["version"]}'
checks={"version":case["version"],"stats":[step["summary"] for step in case["steps"]]}
west,south=case["bounds"][0];east,north=case["bounds"][1]
lon,lat=(west+east)/2,(south+north)/2
z=15
x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
paths=[step["wmts"].format(z=z,x=x,y=y) for step in case["steps"]]
checks["wmts"]=[]
for path in paths:
    timings=[]
    for _ in range(5):
        start=time.perf_counter();tile,headers=fetch(path);timings.append(round((time.perf_counter()-start)*1000,2))
        assert tile.startswith(b"\x89PNG\r\n\x1a\n")
    checks["wmts"].append({"samples_ms":timings,"cache":headers.get("geowebcache-cache-result",headers.get("Geowebcache-Cache-Result")),"bytes":len(tile)})
tile,headers=fetch(f"{v2}/tiles/{z}/{x}/{y}.pbf")
assert len(tile)>100
checks["mvt"]={"bytes":len(tile),"type":headers.get("content-type",headers.get("Content-Type")),"tile":[z,x,y]}
(out/"sample.pbf").write_bytes(tile)
check_path=f"{v2}/sample?step=ida&lon={lon}&lat={lat}"
sample=get(check_path)
assert sample["status"] in {"water","covered","no_coverage"}
checks["point"]=sample
assert code("/api/v2/imports",headers={"Origin":base},method="POST")==401
assert code("/api/v2/imports",headers=auth|{"Origin":"https://example.org"},method="POST")==403
assert code(f"{v2}/tiles/{z}/{x}/{y}.pbf?CQL_FILTER=1%3D1")==422
checks["security"]={"missing_key":401,"foreign_origin":403,"CQL_FILTER":422}
versions = root/"data/processed/teaching-v1/74e68b2da680e9680f65"
rasters = sorted((versions/"rasters").glob("*S02*T*.tif"))
if len(rasters)!=3:
    rasters = sorted((versions/"rasters").glob("*S02*.tif"))
assert len(rasters)==3, [p.name for p in (versions/"rasters").iterdir()]
metadata={"id":"qa-cross-region","title":"跨区导入验收样例","subtitle":"EPSG:32650","unit":"m","threshold_m":.1,
          "srid":32650,"steps":[{"id":f"time-{m}","label":f"{m} 分钟","scenario":"验收过程","kind":"time","time_min":m}
                               for m in (0,30,60)]}
form=[("metadata",json.dumps(metadata)), *(("depths",path) for path in rasters),("buildings",versions/"teaching.gpkg"),("roads",versions/"teaching.gpkg")]
headers,data=multipart(form)
started=get("/api/v2/imports",headers,data,"POST")
job=started["id"]
assert code(f"/api/v2/imports/{job}/publish",auth,method="POST")==409
preview=wait(job,{"preview"})
assert preview["case"]["analysis_srid"]==32650
assert preview["case"]["steps"][0]["summary"]["flooded_area_m2"]==0
get(f"/api/v2/imports/{job}/publish",auth,method="POST")
ready=wait(job,{"ready"})
published=ready["case"]
endpoint=f'/api/v2/cases/{published["id"]}/{published["version"]}'
export=out/"qa-cross-region.zip"
export.write_bytes(fetch(endpoint+"/export",auth)[0])
head,body=multipart([("archive",export)])
again=get("/api/v2/imports",head,body,"POST")
wait(again["id"],{"preview"})
get(f'/api/v2/imports/{again["id"]}/publish',auth,method="POST")
assert wait(again["id"],{"ready"})["case"]["version"]==published["version"]
checks["cross_region"]={"epsg":32650,"counts":preview["preview"],"same_hash_on_reimport":True,
                        "export_sha256":hashlib.sha256(export.read_bytes()).hexdigest()}
checks["concurrency"]=[]
for workers in (5,10,20):
    def request(_):
        start=time.perf_counter(); assert get(check_path)==sample; return (time.perf_counter()-start)*1000
    with ThreadPoolExecutor(max_workers=workers) as pool:
        values=sorted(pool.map(request,range(workers*8)))
    checks["concurrency"].append({"workers":workers,"requests":len(values),"p95_ms":round(values[math.ceil(.95*len(values))-1],2)})
(out/"api-checks.json").write_text(json.dumps(checks,indent=2,ensure_ascii=False),encoding="utf-8")
print("PASS NYC WMTS, MVT, API guards, cross-region file upload, export, reimport, and limited concurrency")

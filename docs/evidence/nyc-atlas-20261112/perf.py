import json,math,time,urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
out=Path("work/nyc-final-20261112")
start=urllib.request.build_opener(urllib.request.ProxyHandler({}))
base="http://127.0.0.1:5173"
def get(path):
    before=time.perf_counter()
    with start.open(base+path,timeout=15) as r:
        return r.read(),r.headers.get("geowebcache-cache-result"),round((time.perf_counter()-before)*1000,2)
catalog=json.loads(get("/api/v2/cases")[0])
case=next(c for c in catalog["cases"] if c["id"]=="nyc-ida")
(w,s),(e,n)=case["bounds"]
lon,lat=w+(e-w)*.46,s+(n-s)*.54
z=18;x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
runs=[]
for step in case["steps"]:
    path=step["wmts"].format(z=z,x=x,y=y)
    readings=[get(path) for _ in range(6)]
    assert len({image for image,_,_ in readings})==1
    runs.append({"step":step["id"],"tile":[z,x,y],"requests":[{"cache":cache,"ms":ms} for _,cache,ms in readings]})
path=f'/api/v2/cases/nyc-ida/{case["version"]}/sample?step=ida&lon={lon}&lat={lat}'
ref=get(path)[0]
capacity=[]
for size in (5,10,20):
    def fetch(_):
        value,_,latency=get(path)
        assert value==ref
        return latency
    with ThreadPoolExecutor(max_workers=size) as pool:
        values=sorted(pool.map(fetch,range(size*8)))
    capacity.append({"concurrency":size,"requests":len(values),"p95_ms":values[math.ceil(len(values)*.95)-1]})
(out/"perf.json").write_text(json.dumps({"wmts":runs,"sample":capacity},indent=2),encoding="utf-8")
print(json.dumps({"wmts":runs,"sample":capacity}))

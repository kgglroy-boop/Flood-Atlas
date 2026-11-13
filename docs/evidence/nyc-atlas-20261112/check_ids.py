import json
import subprocess
from pathlib import Path

root=Path("work/nyc-final-20261112")
rows=json.loads((root/"qgis-checks.json").read_text(encoding="utf-8"))
verified={}
for row in rows:
    sid=row["id"]
    sql=("SELECT building_id FROM case_v2.building_steps WHERE affected AND case_id='nyc-ida' "
         f"AND version='bf37267f4becb2844107' AND step_id='{sid}';")
    db=set(subprocess.check_output(["docker","compose","exec","-T","db","psql","-U","flood","-d","flood",
                                     "-v","ON_ERROR_STOP=1","-Atc",sql],text=True).splitlines())
    assert db == set(row["affected_ids"])
    assert row["area_m2"] == row["service"]["flooded_area_m2"]
    assert row["road_length_m"] == row["service"]["flooded_road_length_m"]
    verified[sid]={"equal_building_id_sets":True,"building_count":len(db),"area_m2":row["area_m2"],
                   "road_length_m":row["road_length_m"]}
(root/"qgis-match.json").write_text(json.dumps(verified,indent=2),encoding="utf-8")
print("PASS_QGIS_MATCH",verified)


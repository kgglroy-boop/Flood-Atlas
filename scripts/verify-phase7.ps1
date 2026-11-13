#requires -Version 7.0
param([switch]$RunExperiments,[string]$QgisPython='C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/performance-common.ps1"
. "$PSScriptRoot/engineering-common.ps1"
. "$PSScriptRoot/gwc-common.ps1"
Assert-ProjectDocker;Assert-AuditServices
$directory=Resolve-TeachingDataset -OutputRoot (Join-Path $ProjectRoot 'data/processed/teaching-v1')
Assert-PublishedTeachingDataset $directory
$base=Join-Path $ProjectRoot 'data/processed/_checks/phase7/verification'
$run='run-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
$root=Join-Path $base $run;$null=New-Item -ItemType Directory $root -Force
$succeeded=$false
try {
 $data=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.data','verify','--contract',(Join-Path $ProjectRoot 'data/metadata/data-contract.json'),'--dataset-dir',$directory)
 $database=Invoke-TeachingDatabase -DatasetDirectory $directory -VerifyOnly
 $raw=Invoke-DataProcess -FilePath (Get-Command docker).Source -ArgumentList @('compose','exec','-T','backend','python','-m','app.engineering_audit')
 $inventory=$raw|ConvertFrom-Json -AsHashtable
 $reference=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.engineering.reference','--gpkg',(Join-Path $directory 'teaching.gpkg'))
 $reference=$reference|ConvertTo-Json -Depth 8|ConvertFrom-Json -AsHashtable
 Assert-AuditAreas $inventory $reference
 $inventory|ConvertTo-Json -Depth 10|Set-Content (Join-Path $root 'inventory.json') -Encoding utf8
 $reference|ConvertTo-Json -Depth 8|Set-Content (Join-Path $root 'qgis-areas.json') -Encoding utf8
 & "$PSScriptRoot/audit-security.ps1"
 foreach($port in @(8000,5173)){
  Assert-HealthyApi "http://127.0.0.1:$port/api/v1/health"
  $tileRoot=Join-Path $root "mvt-$port"
  $null=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.engineering.check_tiles','--root',$tileRoot,'--gpkg',(Join-Path $directory 'teaching.gpkg'),'--download','--port',"$port")
 }
 $target=Get-GwcAuditTarget;$bbox=($target.tile|ForEach-Object{$_.ToString('R',[Globalization.CultureInfo]::InvariantCulture)})-join ','
 foreach($scenario in @('S01','S02')){foreach($minute in @(0,30,60)){
  $step='{0}_T{1:00}' -f $scenario,$minute;$layer="flood:depth_$step"
  $tile=Join-Path $root "$step-wmts.png";$wms=Join-Path $root "$step-wms.png"
  $url=Get-GwcTileUrl $layer $target.z $target.x $target.y
  $r=Invoke-WebRequest -NoProxy -Uri $url -OutFile $tile -PassThru -TimeoutSec 30
  if($r.StatusCode -ne 200 -or ([string]($r.Headers['geowebcache-cache-result']-join '')) -notin @('HIT','MISS')){throw 'WMTS response not served by GWC.'}
  $encoded=[Uri]::EscapeDataString($layer)
  $null=Invoke-WebRequest -NoProxy -Uri "http://127.0.0.1:8080/geoserver/flood/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=$encoded&STYLES=&SRS=EPSG:900913&BBOX=$bbox&WIDTH=256&HEIGHT=256&FORMAT=image%2Fpng&TRANSPARENT=true&INTERPOLATIONS=nearest%20neighbor" -OutFile $wms -TimeoutSec 30
  $null=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.engineering.check_cache','--cold',$tile,'--hot',$tile,'--wms',$wms)
 }}
 if($RunExperiments){
  $gist=Invoke-DataProcess -FilePath (Get-Command docker).Source -ArgumentList @('compose','exec','-T','backend','python','-m','app.engineering_audit','--gist-experiment')
  $gist|Set-Content (Join-Path $root 'gist.json') -Encoding utf8
  & "$PSScriptRoot/measure-gwc.ps1" -QgisPython $QgisPython
  & "$PSScriptRoot/measure-api.ps1" -QgisPython $QgisPython
 }
 Assert-AuditServices;$succeeded=$true
} finally {
 [ordered]@{status=$(if($succeeded){'ok'}else{'failed'});captured_at=(Get-Date -Format o);experiments=[bool]$RunExperiments;generation_id=(Split-Path $directory -Leaf);scope='File hashes, database snapshot, metric sample areas, API security/health, six WMTS/WMS decoded PNG comparisons, 200 MVT IDs through both ports';limitation='Administrator database role retained; owner visual acceptance remains separate.'}|ConvertTo-Json|Set-Content (Join-Path $root 'verification.json') -Encoding utf8
}
@{run=$run}|ConvertTo-Json|Set-Content (Join-Path $base 'latest.json') -Encoding utf8
Write-Host '[PASS] phase7 engineering verification; no experiments run unless -RunExperiments'

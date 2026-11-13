#requires -Version 7.0
param([string]$QgisPython='C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/geoserver-common.ps1"
. "$PSScriptRoot/gwc-common.ps1"
$directory=Resolve-TeachingDataset -OutputRoot (Join-Path $ProjectRoot 'data/processed/teaching-v1')
Assert-PublishedTeachingDataset -DatasetDirectory $directory
$manifest=Get-Content (Join-Path $directory 'manifest.json') -Raw|ConvertFrom-Json
$sld=Get-Content (Join-Path $ProjectRoot 'geoserver/styles/depth_teaching.sld') -Raw
$signature=ConvertTo-SldSignature $sld
foreach($layer in @(Get-TeachingLayerCatalog)){
 Assert-TeachingResources (Get-TeachingResources $layer.store_name) "file:/opt/project_data/teaching-v1/$($manifest.generation_id)/rasters/$($layer.raster_name)" $signature $layer.store_name
}
$target=Get-GwcAuditTarget
$url=Get-GwcTileUrl $target.layer $target.z $target.x $target.y
$base=Join-Path $ProjectRoot 'data/processed/_checks/phase7/gwc'
$run='run-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
$root=Join-Path $base $run
$null=New-Item -ItemType Directory -Path $root -Force
$bbox=($target.tile|ForEach-Object{$_.ToString('R',[Globalization.CultureInfo]::InvariantCulture)})-join ','
$wms="$root/wms.png"
$null=Invoke-WebRequest -NoProxy -Uri "http://127.0.0.1:8080/geoserver/flood/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=flood%3Adepth_S02_T60&STYLES=&SRS=EPSG:900913&BBOX=$bbox&WIDTH=256&HEIGHT=256&FORMAT=image%2Fpng&TRANSPARENT=true&INTERPOLATIONS=nearest%20neighbor" -OutFile $wms -TimeoutSec 30
$samples=@(foreach($round in 1..5){
 Invoke-GwcAuditTruncate
 foreach($sample in 0..5){
  $path="$root/r$round-s$sample.png"
  $watch=[Diagnostics.Stopwatch]::StartNew()
  $r=Invoke-WebRequest -NoProxy -Uri $url -OutFile $path -PassThru -TimeoutSec 30
  $watch.Stop();$result=[string]($r.Headers['geowebcache-cache-result']-join '')
  $expected=if($sample -eq 0){'MISS'}else{'HIT'}
  [pscustomobject]@{round=$round;sample=$sample;cache=$result;status=[int]$r.StatusCode;milliseconds=$watch.Elapsed.TotalMilliseconds}|Export-Csv -LiteralPath "$root/samples.csv" -NoTypeInformation -Append -Encoding utf8
  if($r.StatusCode -ne 200 -or $result -cne $expected){throw 'Actual GWC cache state did not match controlled cold/hot experiment.'}
  if($sample -gt 0){$null=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.engineering.check_cache','--cold',"$root/r$round-s0.png",'--hot',$path,'--wms',$wms)}
  [ordered]@{round=$round;sample=$sample;cache=$result;status=[int]$r.StatusCode;milliseconds=$watch.Elapsed.TotalMilliseconds;file=(Split-Path $path -Leaf)}
 }
})
$report=[ordered]@{status='ok';captured_at=(Get-Date -Format o);generation_id=$manifest.generation_id;url=$url;grid='EPSG:900913 (Web Mercator alias)';target=$target;samples=$samples;limitation='Five cold samples only; no required speedup ratio or production capacity claim.'}
$report|ConvertTo-Json -Depth 12|Set-Content (Join-Path $root 'measurement.json') -Encoding utf8
@{run=$run}|ConvertTo-Json|Set-Content (Join-Path $base 'latest.json') -Encoding utf8
Write-Host '[PASS] five controlled cold MISS / five hot HIT rounds; decoded PNGs match uncached WMS'

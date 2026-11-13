#requires -Version 7.0
param([Parameter(Mandatory)][string]$RunName,[Parameter(Mandatory)][string]$ReportPath,[string]$QgisPython,[switch]$KeepRunning)
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/rebuild-common.ps1"
. "$PSScriptRoot/geoserver-common.ps1"
. "$PSScriptRoot/gwc-common.ps1"
Assert-RebuildOwnership $RunName $RunName
$env:COMPOSE_PROJECT_NAME=$RunName;$env:COMPOSE_PATH_SEPARATOR=';'
$env:COMPOSE_FILE="$ProjectRoot/docker-compose.yml;$ProjectRoot/docker-compose.rebuild.yml"
# This process is isolated from the parent; don't inherit shell credential overrides.
foreach($line in Get-Content "$ProjectRoot/.env"){
 if($line -match '^(POSTGRES_PASSWORD|GEOSERVER_ADMIN_PASSWORD)=([A-F0-9]{48})$'){[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}
}
function Invoke-GeoServerRequest([string]$Method='GET',[string]$Path,[string]$Body='',[string]$ContentType='application/json') {
 if(-not $Path.StartsWith('/') -or $Path.Contains('..') -or $Path.Contains('://')){throw 'Invalid isolated REST path'}
 try{
  $options=@{Uri="http://127.0.0.1:18080/geoserver/rest$Path";Method=$Method;Headers=(Get-GeoServerHeaders);NoProxy=$true;SkipHttpErrorCheck=$true;TimeoutSec=30}
  if($Body){$options.Body=[Text.Encoding]::UTF8.GetBytes($Body);$options.ContentType=$ContentType}
  $reply=Invoke-WebRequest @options
  return @{StatusCode=[int]$reply.StatusCode;Content=(ConvertFrom-GeoServerContent $reply.Content);Headers=$reply.Headers}
 }catch{throw 'Isolated GeoServer REST unavailable; credentials omitted.'}
}
function Get-RebuildJson([string]$Uri){
 $r=Invoke-WebRequest -NoProxy -Uri $Uri -TimeoutSec 15
 if($r.StatusCode -ne 200){throw 'Isolated API unavailable'}
 return ($r.Content|ConvertFrom-Json -AsHashtable)
}
$ok=$false;$started=$false;$step='configuration';$checks=[Collections.Generic.List[object]]::new();$directory=$null;$empty=$null
Push-Location $ProjectRoot
try{
 $configuration=(@(Invoke-ProjectCompose @('config','--format','json'))-join "`n")|ConvertFrom-Json -AsHashtable
 Assert-RebuildConfiguration $configuration $RunName
 $step='generate';Write-Host 'REBUILD: regenerate from committed tools; no copied scientific data'
 $generated=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.data','generate','--contract',"$ProjectRoot/data/metadata/data-contract.json",'--output-root',"$ProjectRoot/data/processed/teaching-v1",'--sources',"$ProjectRoot/data/processed/_checks/rebuilt-sources.csv")
 $directory=$generated.dataset_dir
 $null=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.delivery.map_package','--dataset',$directory,'--output',"$ProjectRoot/frontend/public/maps/teaching-snapshot")
 $step='services';$started=$true
 $null=Invoke-ProjectCompose @('up','-d','--build','--wait','--wait-timeout','240')
 $empty=(@(Invoke-ProjectCompose @('exec','-T','db','psql','-U','flood','-d','flood','-Atc',"SELECT count(*) FROM information_schema.schemata WHERE schema_name='flood';"))-join '').Trim()
 if($empty -ne '0'){throw 'Reconstruction database not empty before import.'}
 $step='import';$import=Invoke-TeachingDatabase -DatasetDirectory $directory
 $step='publication'
 Write-RestResource 'POST' '/workspaces' '{"workspace":{"name":"flood"}}'
 Write-RestResource 'PUT' '/namespaces/flood.json' '{"namespace":{"prefix":"flood","uri":"https://example.org/urban-flood"}}'
 $publication=Ensure-Phase4Publication -GenerationId $generated.generation_id -SldPath "$ProjectRoot/geoserver/styles/depth_teaching.sld"
 $step='analysis';$reference=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.analysis.reference','--gpkg',"$directory/teaching.gpkg")
 $artifactRoot=Join-Path (Split-Path $ReportPath -Parent) 'checks';$null=New-Item -ItemType Directory $artifactRoot -Force
 foreach($port in @(18000,15173)){
  Assert-HealthyApi "http://127.0.0.1:$port/api/v1/health"
  $catalog=Get-RebuildJson "http://127.0.0.1:$port/api/v1/scenarios";$summaries=@{};$collections=@{}
  foreach($scenario in @('S01','S02')){foreach($minute in @(0,30,60)){
   $id='{0}_T{1:00}' -f $scenario,$minute
   $summaries[$id]=Get-RebuildJson "http://127.0.0.1:$port/api/v1/analysis/summary?step_id=$id"
   $collections[$id]=Get-RebuildJson "http://127.0.0.1:$port/api/v1/analysis/buildings?step_id=$id"
  }}
  $input=Join-Path $artifactRoot "analysis-$port.json"
  @{catalog=$catalog;reference=$reference;summaries=$summaries;collections=$collections}|ConvertTo-Json -Depth 40|Set-Content $input -Encoding utf8
  $checked=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.analysis.check_responses','--input',$input)
  $checks.Add(@{type='analysis';port=$port;result=$checked})
  $tileRoot=Join-Path $artifactRoot "mvt-$port"
  foreach($x in 27032..27036){foreach($y in 13440..13444){
   $path=Join-Path $tileRoot "15/$x/$y.pbf";$null=New-Item -ItemType Directory (Split-Path $path -Parent) -Force
   $r=Invoke-WebRequest -NoProxy -Uri "http://127.0.0.1:$port/api/v1/tiles/buildings/15/$x/$y.pbf" -OutFile $path -PassThru -TimeoutSec 15
   if($r.StatusCode -ne 200 -or [string]($r.Headers['Content-Type']-join '') -ne 'application/vnd.mapbox-vector-tile'){throw 'Rebuilt MVT HTTP contract failed.'}
  }}
  $tiles=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.engineering.check_tiles','--root',$tileRoot,'--gpkg',"$directory/teaching.gpkg")
  $checks.Add(@{type='mvt';port=$port;result=$tiles})
 }
 $step='wmts';$target=Get-GwcAuditTarget;$bbox=($target.tile|ForEach-Object{$_.ToString('R',[Globalization.CultureInfo]::InvariantCulture)})-join ','
 foreach($layer in Get-TeachingLayerCatalog){
  $url=(Get-GwcTileUrl $layer.layer_id 15 27034 13441).Replace('127.0.0.1:8080','127.0.0.1:18080')
  $png=Join-Path $artifactRoot "$($layer.step_id)-wmts.png";$wms=Join-Path $artifactRoot "$($layer.step_id)-wms.png"
  $r=Invoke-WebRequest -NoProxy -Uri $url -OutFile $png -PassThru -TimeoutSec 30 -Headers @{Origin='http://localhost:15173'}
  if($r.StatusCode -ne 200 -or [string]($r.Headers['Access-Control-Allow-Origin']-join '') -ne 'http://localhost:15173'){throw 'Isolated WMTS/CORS failed.'}
  $encoded=[Uri]::EscapeDataString($layer.layer_id)
  $null=Invoke-WebRequest -NoProxy -Uri "http://127.0.0.1:18080/geoserver/flood/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=$encoded&STYLES=&SRS=EPSG:900913&BBOX=$bbox&WIDTH=256&HEIGHT=256&FORMAT=image%2Fpng&TRANSPARENT=true&INTERPOLATIONS=nearest%20neighbor" -OutFile $wms -TimeoutSec 30
  $pixels=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.engineering.check_cache','--cold',$png,'--hot',$png,'--wms',$wms)
  $checks.Add(@{type='wmts';step_id=$layer.step_id;result=$pixels})
 }
 $served=Invoke-WebRequest -NoProxy -Uri 'http://127.0.0.1:15173/src/App.vue' -TimeoutSec 15
 if(-not $served.Content.Contains('http://localhost:18080/geoserver')){throw 'Rebuilt frontend does not use isolated GeoServer.'}
 $checks.Add(@{type='frontend-runtime';geoserver='http://localhost:18080/geoserver';checked_served_module=$true})
 $step='finished';$ok=$true
}catch{
 Write-Host "REBUILD FAILED at $step; raw authentication errors omitted."
}finally{
 if($started -and (-not $KeepRunning -or -not $ok)){
  Assert-RebuildOwnership $env:COMPOSE_PROJECT_NAME $RunName
  $null=Invoke-ProjectCompose @('down')
 }
 $validation=if($directory){Get-Content "$directory/validation-report.json" -Raw|ConvertFrom-Json}else{$null}
 [ordered]@{status=$(if($ok){'ok'}else{'failed'});captured_at=(Get-Date -Format o);project=$RunName;last_step=$step;empty_schema_before_import=$empty;generation_id=$(if($directory){Split-Path $directory -Leaf}else{$null});semantic_sha256=$(if($validation){$validation.semantic_sha256}else{$null});checks=$checks.ToArray();kept_running=[bool]($ok -and $KeepRunning);volumes_deleted=$false;scope='Fresh source/no generated data/new volumes; host tools and Docker build/download caches reused.'}|ConvertTo-Json -Depth 18|Set-Content $ReportPath -Encoding utf8
 Pop-Location
}
if(-not $ok){exit 1}
Write-Host '[PASS] rebuilt six rasters, empty database import, six WMTS/WMS and two API/MVT entrances'

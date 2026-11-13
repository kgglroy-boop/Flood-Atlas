#requires -Version 7.0
param([string]$OutputRoot='data/processed/_checks/phase7')
. "$PSScriptRoot/common.ps1"
$start=[DateTime]::UtcNow.AddSeconds(-1).ToString('o')
$marker='PHASE7_'+[guid]::NewGuid().ToString('N')
$attack=[uri]::EscapeDataString($marker+';SELECT 1')
$cases=@(
 @{path="analysis/summary?step_id=$attack";code=422},
 @{path='analysis/summary?step_id=S02_T60&step_id=S01_T30';code=422},
 @{path='analysis/summary?step_id=S02_T60&CQL_FILTER=1%3D1';code=422},
 @{path='analysis/summary?step_id=S02_T60&limit=1';code=422},
 @{path='analysis/buildings?step_id=S02_T60&limit=501';code=422},
 @{path='analysis/buildings?step_id=S02_T60&limit=1&limit=2';code=422},
 @{path='analysis/summary?step_id=S03_T30';code=404}
)
$results=@(foreach($port in @(8000,5173)) {
 foreach($case in $cases){
  $r=Invoke-WebRequest -NoProxy -Uri "http://127.0.0.1:$port/api/v1/$($case.path)" -TimeoutSec 15 -SkipHttpErrorCheck
  if($r.StatusCode -ne $case.code){throw 'Security response contract failed.'}
  $body=[string]$r.Content
  if($body.Contains($marker)-or $body -match 'postgresql://|password=|Traceback'){throw 'Sensitive diagnostic in response.'}
  [ordered]@{port=$port;case_index=([array]::IndexOf($cases,$case)+1);status=[int]$r.StatusCode}
 }
})
foreach($pair in @(@('db',5432),@('geoserver',8080),@('backend',8000),@('frontend',5173))){
 $bound=(& docker compose port $pair[0] $pair[1] 2>$null)-join ''
 if($LASTEXITCODE -or $bound.Trim() -ne "127.0.0.1:$($pair[1])"){throw 'Service is not bound only to the expected loopback port.'}
}
$ignored=@(& git check-ignore .env)
if($LASTEXITCODE -or $ignored -notcontains '.env'){throw 'Local secret file is not ignored.'}
$trackedRuntime=@(& git ls-files -- .env '*/.env' '*/node_modules/*' 'data/processed/*' | Where-Object {$_ -ne 'data/processed/.gitkeep'})
if($trackedRuntime.Count){throw 'Runtime or secret files tracked.'}
$logs=(@(& docker compose logs --since $start --no-log-prefix backend frontend 2>&1)|ForEach-Object{$_.ToString()})-join "`n"
if($LASTEXITCODE -or $logs.Contains($marker)){throw 'Raw query marker present in logs or logs unavailable.'}
$rest=Invoke-WebRequest -NoProxy -Uri 'http://127.0.0.1:8080/geoserver/rest/about/version.json' -TimeoutSec 15 -SkipHttpErrorCheck
if($rest.StatusCode -notin @(401,403)){throw 'GeoServer administrative REST must require authentication.'}
$null=New-Item -ItemType Directory -Path (Join-Path $ProjectRoot $OutputRoot) -Force
[ordered]@{status='ok';captured_at=(Get-Date -Format o);requests=$results;loopback_only=$true;env_ignored=$true;raw_marker_absent=$true;admin_rest_status=[int]$rest.StatusCode;limitations=@('Runtime database user retains administrative privileges by owner choice.','Public WMS/CQL boundary is loopback isolation, not an enterprise input firewall.')} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ProjectRoot "$OutputRoot/security.json") -Encoding utf8
Write-Host '[PASS] API inputs, sanitized logs, loopback ports and administrative REST boundary'

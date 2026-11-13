#requires -Version 7.0
$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location -LiteralPath $root
try {
    $start=[DateTime]::UtcNow.AddSeconds(-1).ToString('o')
    $marker='PHASE5_QUERY_'+[guid]::NewGuid().ToString('N')
    $response=Invoke-WebRequest -NoProxy -Uri "http://127.0.0.1:8000/api/v1/analysis/summary?step_id=$marker%3BSELECT%201" -TimeoutSec 10 -SkipHttpErrorCheck
    if ($response.StatusCode -ne 422) { throw 'Malformed analysis query did not return422.' }
    $logs=(@(& docker compose logs --since $start --no-log-prefix backend 2>&1) | ForEach-Object { $_.ToString() }) -join "`n"
    if ($LASTEXITCODE) { throw 'Could not inspect bounded backend logs.' }
    if ($logs.Contains($marker)) { throw 'Raw rejected analysis query appeared in backend logs.' }
    Write-Host 'PASS: rejected analysis parameters are absent from backend logs'
    $probe=Join-Path $PSScriptRoot 'analysis-proxy-logging.mjs'
    & docker compose run --rm --no-deps -T --volume "${probe}:/tmp/analysis-proxy-logging.mjs:ro" frontend node /tmp/analysis-proxy-logging.mjs
    if ($LASTEXITCODE) { throw 'Isolated frontend proxy logging regression failed.' }
} finally { Pop-Location }

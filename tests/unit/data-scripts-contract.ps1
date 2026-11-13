#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$testRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $testRoot 'scripts/data-common.ps1')

function Assert-DataTest([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$temporary = Join-Path $testRoot ('.superpowers/sdd/2026-10-19-phase2-data-plan/script tests ' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $temporary
$echoScript = Join-Path $temporary 'utf8 echo.ps1'
@'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$value = [Console]::In.ReadToEnd()
$parsed = $value | ConvertFrom-Json
if ($parsed.name -ne "教学建筑 O'Brien") { exit 6 }
[Console]::Out.Write($value)
'@ | Set-Content -LiteralPath $echoScript -Encoding utf8
$payload = @{name="教学建筑 O'Brien"} | ConvertTo-Json -Compress
$reply = Invoke-DataProcess -FilePath (Join-Path $PSHOME 'pwsh.exe') -ArgumentList @('-NoProfile','-File',$echoScript) -InputText $payload
Assert-DataTest (($reply | ConvertFrom-Json).name -eq "教学建筑 O'Brien") 'UTF-8 input/output was changed.'
Write-Host 'PASS: Unicode stdin and executable arguments with spaces'

$failureScript = Join-Path $temporary 'failed child.ps1'
"[Console]::Error.Write('simulated-password-do-not-print'); exit 7" | Set-Content -LiteralPath $failureScript
$failed = $false
try {
    $null = Invoke-DataProcess -FilePath (Join-Path $PSHOME 'pwsh.exe') -ArgumentList @('-NoProfile','-File',$failureScript)
} catch {
    $failed = $true
    Assert-DataTest (-not $_.Exception.Message.Contains('simulated-password')) 'Child error leaked secret.'
}
Assert-DataTest $failed 'Nonzero child exit was ignored.'
Write-Host 'PASS: child failures stop execution without raw secret-bearing output'

$output = Join-Path $temporary 'missing output'
$missing = Join-Path $temporary 'not installed.bat'
$result = & pwsh -NoProfile -File (Join-Path $testRoot 'scripts/prepare-data.ps1') -QgisPython $missing -OutputRoot $output 2>&1
Assert-DataTest ($LASTEXITCODE -ne 0) 'Missing QGIS must fail.'
Assert-DataTest (-not (Test-Path -LiteralPath (Join-Path $output 'latest.json'))) 'Failure published latest.'
Write-Host 'PASS: missing QGIS fails without publishing output'

$fakeQgis = Join-Path $temporary 'failed qgis.bat'
"@echo off`r`nexit /b 7`r`n" | Set-Content -LiteralPath $fakeQgis -Encoding ascii
$result = & pwsh -NoProfile -File (Join-Path $testRoot 'scripts/prepare-data.ps1') -QgisPython $fakeQgis -OutputRoot $output 2>&1
Assert-DataTest ($LASTEXITCODE -ne 0) 'QGIS failure must propagate.'
Assert-DataTest (-not (Test-Path -LiteralPath (Join-Path $output 'latest.json'))) 'Failed QGIS published latest.'
Write-Host 'PASS: generation failure stops before publishing or importing'

$null = New-Item -ItemType Directory -Path $output
'{"generation_id":"x","relative_path":"../outside"}' | Set-Content -LiteralPath (Join-Path $output 'latest.json')
$rejected = $false
try { $null = Resolve-TeachingDataset -OutputRoot $output } catch { $rejected = $true }
Assert-DataTest $rejected 'Unsafe latest pointer was accepted.'
Write-Host 'PASS: out-of-root latest pointer is rejected'

# Temporary outputs are for reproducibility only; Docker publishes the canonical root.
$rejected = $false
try { Assert-PublishedTeachingDataset -DatasetDirectory $temporary } catch {
    $rejected = $_.Exception.Message -like '*发布目录*'
}
Assert-DataTest $rejected 'Non-published datasets must be rejected with an actionable reason.'
Write-Host 'PASS: alternative roots cannot be imported or verified as published data'

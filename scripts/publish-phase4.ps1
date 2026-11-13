#requires -Version 7.0
param([string]$QgisPython = 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/geoserver-common.ps1"
try {
    Assert-ProjectDocker
    $directory = Resolve-TeachingDataset -OutputRoot (Join-Path $ProjectRoot 'data/processed/teaching-v1')
    Assert-PublishedTeachingDataset -DatasetDirectory $directory
    $null = Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.data','verify',
        '--contract',(Join-Path $ProjectRoot 'data/metadata/data-contract.json'),'--dataset-dir',$directory)
    $manifest = Get-Content -LiteralPath (Join-Path $directory 'manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $result = Ensure-Phase4Publication -GenerationId $manifest.generation_id -SldPath (Join-Path $ProjectRoot 'geoserver/styles/depth_teaching.sld')
    Write-Host '[PASS] 六张教学水深已发布并复核；源数据未修改'
    $result | ConvertTo-Json -Depth 5
} catch { Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red; exit 1 }

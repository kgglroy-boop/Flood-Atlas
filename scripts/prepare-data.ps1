#requires -Version 7.0
param([string]$QgisPython = 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat',
      [string]$OutputRoot = '', [string]$SourcesPath = '')
. "$PSScriptRoot/data-common.ps1"
try {
    if (-not $OutputRoot) { $OutputRoot = Join-Path $ProjectRoot 'data/processed/teaching-v1' }
    if (-not $SourcesPath) { $SourcesPath = Join-Path $ProjectRoot 'data/metadata/sources.csv' }
    $result = Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.data','generate',
        '--contract',(Join-Path $ProjectRoot 'data/metadata/data-contract.json'),
        '--output-root',[IO.Path]::GetFullPath($OutputRoot),'--sources',[IO.Path]::GetFullPath($SourcesPath))
    Write-Host '[PASS] 六张栅格、矢量、QGIS 项目与图集已生成并校验'
    $result | ConvertTo-Json -Depth 6
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

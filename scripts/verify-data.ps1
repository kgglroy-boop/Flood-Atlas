#requires -Version 7.0
param([string]$QgisPython = 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat',
      [string]$OutputRoot = '')
. "$PSScriptRoot/data-common.ps1"
try {
    if (-not $OutputRoot) { $OutputRoot = Join-Path $ProjectRoot 'data/processed/teaching-v1' }
    $directory = Resolve-TeachingDataset -OutputRoot $OutputRoot
    Assert-PublishedTeachingDataset -DatasetDirectory $directory
    $files = Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.data','verify',
        '--contract',(Join-Path $ProjectRoot 'data/metadata/data-contract.json'),'--dataset-dir',$directory)
    $database = Invoke-TeachingDatabase -DatasetDirectory $directory -VerifyOnly
    Assert-HealthyApi
    $report = [ordered]@{status='ok';captured_at=(Get-Date -Format o);files=$files;database=$database;api='healthy'}
    Write-Host '[PASS] 文件、数据库、索引、逐步面积与健康接口均已核验'
    $report | ConvertTo-Json -Depth 10
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
